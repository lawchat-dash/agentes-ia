# Mudanças no papel "desqualificado" (motor LawChat, Sousa e Costa)

**Onde entra:** o conteúdo de `desqualificado.md` substitui o campo `instrucao` da etapa `codigo = "desqualificado"`
em `agente.etapas` do snapshot (`sousa_costa.json`). `config.catalogo.papeis.desqualificado` não muda:
`mensagem_troca` idêntica, `boas_vindas` continua `null`, `destinos` continua `[]` e as ferramentas continuam desligadas.

**Ponto de partida:** a instrução fiel (`sousa_costa.json`), a troca D1/D2 de `sousa_costa_sugerido.json` e o
rascunho `n8n/06_DESQUALIFICADO.txt`. Do rascunho saíram a tabela MOTIVO REAL, as regras de preenchimento e a
ordem das respostas. Tudo o que era do n8n foi tirado ou trocado: a tool `encerramento`, `{{ $now }}` e "a data de
hoje do início deste prompt". No nosso motor, a data vem na linha "Hoje é…" do conteúdo, o encerramento é do sistema
e a conversa marca a IA como "você:".

**O que ficou igual:** os 14 títulos, na mesma ordem; as tabelas de travas, critérios e pontos do fluxo; as mensagens
exatas das etapas 2, 3 e 4 e do ENCERRAMENTO; os 7 links (avaliação no Google 2x, imagem de outros benefícios,
Instagram, TikTok, site, YouTube); endereço, e-mail, CNPJ e OABs; as REGRAS DE ATENDIMENTO originais, inclusive a
linha "Faça uma pergunta por vez." repetida.

**Por que a 0523 ainda errou, com a 1ª leva de correções (D1/D2):**
1. A D1 pôs a regra do motivo numa linha **separada** do modelo, mas o modelo continuava com `[tendo/não tendo]
   recebido auxílio-doença`. O gpt-4.1-mini a 0.5 segue o modelo literal e lê a regra solta como comentário. Por
   isso escreveu "não tendo recebido auxílio-doença" mesmo com a regra dizendo que isso não é motivo.
2. A vaga do motivo tinha **três exemplos entre aspas**, e o modelo copiou o primeiro: "fazia tempo demais que você
   estava sem carteira" para quem disse "nunca trabalhei de carteira".
3. A D1 não mexeu na **ordem** das respostas. A confirmação ("me avisa se algo mudou…") não tem "?", então a regra
   "uma pergunta por resposta" do motor não a vê como pergunta. O "obrigado mesmo assim" do lead soa como despedida, e o
   fim do prompt dizia "sempre finalize primeiro pedido de avaliação". Juntando isso, o modelo pediu a nota no mesmo
   turno.
4. O `;` do modelo mantinha a confirmação colada no resumo, como uma frase só.

---

## 1. Ordem das respostas por passo, lida da conversa (novo bloco no topo do FLUXO DE ENCERRAMENTO)

**Problema visto:** confirmação e pedido de nota no mesmo turno, sem esperar o lead. Casos: sc13[ja_recebe_auxilio_acidente]
0317 T4, sc15[nunca_clt] 0426 T9 e **sc15[nunca_clt] 0523 T8** (já com D1/D2).

**ANTES:** `# FLUXO DE ENCERRAMENTO` seguido direto de `## REGRAS DE DESQUALIFICAÇÃO`. Nenhuma regra dizia em que
resposta vai cada etapa.

**DEPOIS:** um novo `## QUAL RESPOSTA MANDAR AGORA (confira antes de escrever)` com:
- "A frase "Analisei com atenção…" já foi enviada ao lead na passagem para esta etapa. Não a repita."
- PASSO A: resumo e confirmação só. "A confirmação "me avisa se algo mudou…" já é a pergunta desta resposta: depois
  dela não escreva mais nada. Mesmo que o lead tenha agradecido ou se despedido (ex.: "ah entendi, obrigado mesmo
  assim"), NÃO peça a nota." A única exceção é o lead que já disse que algo mudou.
- PASSO B: depois da resposta ao resumo, o pedido de nota.
- PASSO C: depois da nota, o fecho inteiro (Google se 5, etapa 4, ENCERRAMENTO), sem pergunta.
- PASSO D: depois do fecho, uma frase cordial, sem repetir nada.
- Se a nota já veio antes do pedido, vai direto ao PASSO C.

**Por quê:** "1ª resposta / 2ª resposta" depende de o modelo contar turnos. "Olhe a sua última linha 'você:'" é uma
checagem que ele consegue fazer em cada turno. Chamar a confirmação de "a pergunta desta resposta" liga o PASSO A à
regra de uma pergunta do motor, e o "obrigado mesmo assim" citado é o gatilho exato do erro. A frase de troca é citada
igual à do snapshot, porque o motor já a insere na passagem (`_com_frase_de_troca`). O PASSO D fecha o laço de mandar a
nota e os links de novo.

## 2. "A desqualificação já foi decidida" (fim das REGRAS DE DESQUALIFICAÇÃO)

**Problema visto:** risco no caminho "a situação mudou". O papel não tem destino (`destinos: []`), então um modelo que
volta a qualificar escreveria uma frase de passagem ou pediria dados sem conseguir transferir. É a classe de falha
"mudar de etapa sem a frase exata" que o usuário relatou, só que aqui sem saída nenhuma.

**ANTES:** nada depois da tabela "Pontos do Fluxo".
**DEPOIS:** "A desqualificação já foi decidida antes desta etapa. Aqui você não reavalia o caso: só confirma o resumo,
explica o motivo e encerra."
**Por quê:** as tabelas de travas ficam (são do escritório), mas deixam claro que servem para o motivo, não para refazer
a análise.

## 3. Modelo do resumo: dois balões, sem travessão nem `;`, com a vaga do motivo e o auxílio-doença só se houve

**Problema visto:**
- ", ," no resumo: sc13[aposentada] 0317 T5, sc13[ja_recebe] 0317 T4, sc15 (3 variantes) 0317, sc16 (2 variantes)
  0317 T11 e sc17[sem_documentos] 0317 T6.
- Motivo falso ou ausente, com "MEI" e "não tendo recebido auxílio-doença" lidos como motivo: sc15[saiu_ha_mais_de_3_anos]
  0317 T7, sc17[sem_documentos] 0317 T6, sc15[nunca_clt] 0426 T9, sc16[sem_seguro] 0426 T13 e **sc15[nunca_clt] 0523 T8**.
- O `;` deixava a confirmação colada no resumo (0523 T8).

**ANTES (fiel):**
```
Pelo que você me contou — acidente [ocorrido em…], do tipo [tipo…], com sequelas [sequelas…], estando você [situação de trabalho…] e [tendo/não tendo] recebido auxílio-doença [período…] —, esse benefício não se aplica ao seu caso; só quero confirmar se entendi tudo certo antes de te dar uma resposta final, então me avisa se algo mudou, está incompleto ou eu entendi errado.
```
(Na sugerida havia também `[ocorrido em: ano informado pelo lead, ou "ano não informado"]` e `como [motivo real: ex. "…" / "…" / "…"]`.)

**DEPOIS:**
```
Balão 1 (o resumo):
Pelo que você me contou, acidente [ocorrido em…], do tipo [tipo…], com sequelas [sequelas…], estando você [situação de trabalho…] [e tendo recebido auxílio-doença por…], como [motivo real…], esse benefício não se aplica ao seu caso.

Balão 2 (a confirmação, sempre com este texto):
Só quero confirmar se entendi tudo certo antes de te dar uma resposta final, então me avisa se algo mudou, está incompleto ou eu entendi errado.
```
**Por quê:** o gpt-4.1-mini obedece ao modelo, então a correção tem que estar no próprio modelo. Sem travessão e sem
`;`, não sobra pontuação quebrada. O "não tendo" saiu do texto e só existe a forma afirmativa opcional. A vaga do motivo
cumpre o OBJETIVO ("Explicar … o motivo"). O texto da confirmação é palavra por palavra o do escritório, com maiúscula
porque agora abre o próprio balão.

## 4. "Como preencher": a data só pela fala do lead, item vazio sai inteiro, checagem final

**Problema visto:** ano ou data que o lead nunca disse. "acidente ocorrido em 2026": sc13[ja_recebe] 0317 T4,
sc15[saiu] 0317 T7, sc17[sem_documentos] 0317 T6 e sc16[sem_seguro] 0317 T11. "março de 2026" ou "03/2026": sc15[nunca_clt],
sc15[teve_clt] e sc16[com_seguro] 0317. É o ano da linha "Hoje é…" do conteúdo, ou um `acidente_ano` errado que o
extrator gravou a partir de "até hj" (analise_rodada2, classe motor). O "ano não informado" da D1 evitava o erro, mas sai
estranho para o lead.

**ANTES:** nenhuma instrução de preenchimento.
**DEPOIS (trecho):**
```
* [ocorrido em…]: a data do acidente do jeito que o lead escreveu numa mensagem dele (formato: "ocorrido em agosto de 2017", "ocorrido em 2017", "ocorrido há uns dois anos"). Se você não acha a data do acidente numa fala do lead, apague "ocorrido em…" e escreva só "acidente do tipo…". A linha "Hoje é…" do começo do conteúdo é a data de hoje, nunca a do acidente. Não tire o ano de outra data (saída do emprego, aposentadoria, auxílio-doença) e nunca faça conta para chegar a um ano. Se o conteúdo disser "Data do acidente: o lead ainda não informou", não fale de data.
…
* Item que falta sai inteiro, com a vírgula dele. Antes de enviar, confira: o balão não pode ter colchetes, reticências (…), travessão (—), ponto e vírgula, vírgula dobrada (", ,"), "não informado" nem dado que o lead não disse.
* Se quem escreve fala por outra pessoa (pai, marido, esposa), troque "você" por "ele" ou "ela" …
```
**Por quê:** a fonte da data passa a ser a fala do lead, e não os DADOS JÁ INFORMADOS. Assim, um ano errado do extrator
não chega ao resumo. A regra cita os dois sinais que o nosso motor manda no conteúdo: a linha "Hoje é…" e a linha "Data
do acidente: o lead ainda não informou" (`turno.py`). "Não tire o ano de outra data" cobre o sc15[saiu], em que "saí em
2019, uns 5 anos antes" convida a fazer a conta. A checagem final lista o que já saiu quebrado nos testes.

## 5. Situação de trabalho na data do acidente; aposentadoria só no motivo

**Problema visto:** sc13[aposentada_por_invalidez] **0523 T6**: "estando você aposentada desde 2021, como você já é
aposentada". A situação de hoje foi parar na vaga da época do acidente, e o motivo saiu repetido. O mesmo aconteceu em
0426 T6 e em 0317 T5. A lead era registrada na confecção na data.

**ANTES:** `[situação de trabalho…]` sem explicação.
**DEPOIS:** "[situação de trabalho…]: como o lead trabalhava NA DATA DO ACIDENTE (ex.: "trabalhando de carteira
assinada", "trabalhando por conta como MEI", "desempregado"). Aposentadoria e benefício que ele recebe hoje não entram
aqui: entram só no [motivo real…], quando forem o motivo."
**Por quê:** cada fato fica numa vaga só. O resumo não se repete e não troca a época.

## 6. Auxílio-doença só se o lead recebeu

**Problema visto:** "não tendo recebido auxílio-doença" em quase todo resumo (0317, 0426 e **0523 T8**). Ao lado de
"esse benefício não se aplica", soa como motivo. É uma opinião jurídica inventada: auxílio-doença prévio não é requisito.

**ANTES:** `e [tendo/não tendo] recebido auxílio-doença [período…]`
**DEPOIS:** `[e tendo recebido auxílio-doença por…]`, com a regra: "só se o lead contou que recebeu auxílio-doença, com
o período que ele disse. Se ele não recebeu ou não falou, apague a parte inteira, com o "e", e não fale de
auxílio-doença no resumo: não ter recebido auxílio-doença não é motivo de nada."
**Por quê:** o que não é motivo não aparece no resumo da desqualificação. A forma negativa não aparece escrita em
lugar nenhum do prompt (nem como proibição entre aspas): no gpt-4.1-mini, a frase citada como "nunca escreva X" também
serve de modelo para copiar.

## 7. Tabela MOTIVO REAL (uma linha por situação) e saída sem motivo inventado

**Problema visto:** **sc15[nunca_clt] 0523 T8**: a lead disse "nunca trabalhei de carteira nao, sempre por conta", e o
resumo disse "como fazia tempo demais que você estava sem carteira assinada antes do acidente". É o 1º exemplo da vaga
da D1.

**ANTES (sugerida):** `como [motivo real: ex. "fazia tempo demais que você estava sem carteira assinada antes do acidente" / "não há documento da época que prove o trabalho rural" / "você já recebe auxílio-acidente"]`
**DEPOIS:** a tabela "O que o lead contou → Frase para [motivo real…]", com 11 linhas: aposentado, já recebe
auxílio-acidente, NUNCA teve carteira, saiu tempo demais antes, não trabalhava na época, rural sem documento, servidor
estatutário, AVC/infarto, doença e não acidente, sem sequela, já pediu e foi negado. Depois dela: "'Nunca teve carteira'
e 'saiu há muito tempo' são motivos diferentes… Ser MEI ou autônomo, por si só, nunca é o motivo. Se nenhuma linha
corresponder com certeza ao que o lead contou, apague "como [motivo real…]," inteiro. Nunca invente um motivo e nunca
acrescente outra explicação jurídica."
A linha do prazo vencido não traz número ("mais de 3 anos" saiu): diz "na data do acidente já tinha passado o prazo
depois da saída da última empresa (o período de graça que a conversa explicou, com ou sem seguro-desemprego)". Com o
número, o desempregado do sc16 (20 meses sem seguro, 0426 T56) não cabia em linha nenhuma e o motivo sumia, ou o
modelo podia repetir "3 anos" ao lead, um prazo que esta etapa não decide.
**Por quê:** a tabela obriga a escolher pela situação, e não pela ordem. As linhas vêm das Travas Absolutas, dos
Critérios Gerais e dos Pontos do Fluxo deste prompt. As de "já recebe", "não trabalhava", "doença" e "negado" vêm da
lista "REGRAS PARA DESQUALIFICAR" e das TRAVAS do SDR, que mandam leads para cá. Todas as frases são de requisito, sem
"direito" e sem previsão. A saída "sem motivo" do rascunho n8n ("pelas informações que você me passou…") encaixada em
"como …" dava uma frase torta. Apagar a oração deixa o resumo correto ("…, esse benefício não se aplica ao seu caso").

## 8. Dois exemplos de formato com dados fictícios

**Problema visto:** sem um exemplo inteiro, o modelo não sabia como fica a frase sem data ou sem auxílio-doença (a
origem das vagas vazias). Também não sabia onde vai a aposentadoria (mudança 5).

**ANTES:** nenhum exemplo.
**DEPOIS:** um exemplo sem data e sem auxílio-doença (motivo NUNCA teve carteira) e um com data e auxílio-doença em que
a pessoa trabalhava de carteira na data e o motivo é a aposentadoria. Os dois têm o rótulo "dados fictícios: nunca copie
o acidente, a sequela, a data nem o período".
**Por quê:** os dois mostram os casos que quebravam. "Queimadura", "óleo quente", "agosto de 2017" e "três meses" não
aparecem em nenhum cenário de teste (conferido no script), então uma cópia seria detectada.

## 9. Etapa 1: só os dois balões nesta resposta; "ok/obrigado" leva à nota

**Problema visto:** o mesmo da mudança 1. O prompt também não dizia o que fazer quando o lead só agradece, que é a
resposta mais comum nos testes.
**ANTES:** nada depois do modelo, além do parágrafo "Se a pessoa disser que a situação mudou…".
**DEPOIS:** "Nesta resposta, envie somente os balões 1 e 2. NÃO peça a nota nesta mesma resposta: espere o lead
responder." e "Se a pessoa confirmar ou só agradecer (ex.: "ok", "entendi", "obrigado mesmo assim"), siga para a etapa 3."
**Por quê:** repete a ordem da mudança 1 no ponto em que o modelo decide.

## 10. "A situação mudou": não perguntar o já dito, e o caso não volta a seguir

**Problema visto:** nenhuma falha nos testes, mas a regra mandava "pergunte o que mudou" mesmo quando o lead já tinha
dito, o que repete pergunta já respondida. Também não cobria o lead que contesta logo na primeira mensagem, e não
impedia o modelo de reabrir a venda (ver mudança 2).
**ANTES:** "…pergunte o que mudou, agradeça e diga que a informação ficou registrada no atendimento. Não refaça as
perguntas de qualificação, não diga que agora ela tem direito e não prometa nova análise. Depois, siga para a etapa 3."
**DEPOIS:** o mesmo parágrafo com "(só se ela ainda não tiver dito)", mais: "Isso vale também se ela contar que mudou
antes de você mandar o resumo: nesse caso não mande o resumo; agradeça, diga que ficou registrado e siga para a etapa
3. Nunca diga que agora o caso pode seguir, nem peça nome ou dados."
**Por quê:** mantém a regra do escritório, sem pergunta repetida e sem um resumo que contradiga o que o lead acabou de
corrigir.

## 11. Etapa 2 (advogado) no lugar do resumo, sem repetir

**Problema visto:** o prompt não dizia se a etapa 2 entra no lugar da etapa 1. No sc12[atuando_hoje] 0317 T3, o SDR já
tinha explicado a ética, e no T4 o Desqualificado foi direto à nota (certo, mas sem regra escrita).
**ANTES:** nada depois da mensagem da etapa 2.
**DEPOIS:** "Quando o motivo for advogado, esta mensagem entra no lugar do resumo da etapa 1 (PASSO A). Envie só ela
nesta resposta e deixe a nota para a próxima. Se a Ana já explicou nesta conversa que não pode seguir por causa do
advogado, não repita: vá direto para a etapa 3."
**Por quê:** a mensagem 2 tem "combinado?". Se a nota viesse junto, seriam duas perguntas.

## 12. Etapa 3: nota sozinha, uma vez só, sem laço

**Problema visto:** o mesmo da mudança 1. Faltava saída para quem responde sem número ("obrigado", "foi bom"), e sem
ela vem a mesma classe de laço vista na Assinatura (sc01 0523). Também não dizia se a etapa 4 vem depois do link do
Google.
**ANTES:** "Mande a seguinte mensagem:" e, depois do link do Google, nada.
**DEPOIS:** "Mande a seguinte mensagem, sozinha, sem outra pergunta na mesma resposta:"; "Peça a nota uma vez só. Vale
como nota 5: "5", "cinco", "5 estrelas", "⭐⭐⭐⭐⭐", "nota máxima". Se o lead responder sem dar uma nota de 1 a 5, não
peça de novo: siga para a etapa 4 … como se a nota fosse inferior a 5."; e, depois do link: "Depois do link, na mesma
resposta, siga para a etapa 4."
**Por quê:** uma pergunta por mensagem e nenhum laço. Nota 5 continua indo ao Google, e as duas notas terminam na etapa 4.

## 13. Etapa 4 emenda com o ENCERRAMENTO; ENCERRAMENTO só no PASSO C

**Problema visto:** "sempre finalize primeiro pedido de avaliação" é ambíguo. Pode ser lido como "peça a avaliação logo"
(uma das causas da mudança 1). Sem a emenda, o modelo pode também parar na imagem.
**ANTES:** depois do link da imagem, nada; e "para concluir, finalize com a mensagem de encerramento acima (não há
ferramenta de encerramento para acionar: o sistema encerra o atendimento), sempre finalize primeiro pedido de avaliação."
**DEPOIS:** "Depois do link, na mesma resposta, envie a mensagem do ENCERRAMENTO." e "…(não há ferramenta de
encerramento para acionar: o sistema encerra o atendimento). Esta mensagem só sai depois que o lead respondeu ao pedido
de avaliação (PASSO C), nunca junto com o resumo nem junto com o pedido de nota."
**Por quê:** a frase ambígua deu lugar a uma ordem explícita. Este papel não tem ferramenta (`acoes: []`), então nada de
tool `encerramento`.

## 14. Novo `## DÚVIDAS DO LEAD NESTA ETAPA` (antes de COMPARTAMENTOS PARA DESATIVAR)

**Problema visto:** a classe "responder dúvida sem retomar a condução", vista em todos os papéis. Nos outros papéis
também apareceram opinião jurídica inventada ("não ter recebido auxílio-doença pode complicar") e promessas. Aqui, o
"mas não tem jeito?" depois da negativa é o momento mais provável para isso.
**ANTES:** nada.
**DEPOIS:** responder em 1 ou 2 frases e seguir o passo que falta (sem pedir a nota de novo no PASSO C/D). "Por quê / não
tem jeito?": repetir o motivo real da tabela e acolher sem prometer (ex.: "Entendo, sei que não é a resposta que você
esperava."), sem "no futuro vai dar certo" nem "outro caminho". Outro benefício: o escritório atua em diversos outros,
sem dizer que ele se encaixa. Credibilidade: os links de Localização e Rede Social. Fora do roteiro: "vai confirmar com
a equipe" (a mesma regra que o motor dá para a base de conhecimento). Nunca inventar.
**Por quê:** dá saída a cada dúvida comum, sem promessa e sem análise nova, e sempre com retorno ao passo.

## 15. REGRAS DE ATENDIMENTO: cinco linhas no fim

**ANTES:** a lista terminava em `* Nunca prometa um áudio.`
**DEPOIS:**
```
* Antes de perguntar, confira a conversa: nunca pergunte o que o lead já respondeu.
* Nunca prometa resultado, nova análise ou outro benefício, e nunca diga que o lead tem direito a algum benefício.
* Nunca dê opinião jurídica além do motivo real da tabela (nada de "isso pode complicar", "seria mais difícil", "talvez dê").
* Nunca cite data, prazo, período ou número que o lead não disse e que este roteiro não traz.
* Nesta etapa não peça documentos, laudo, CPF nem outros dados, e não refaça perguntas de qualificação.
```
**Por quê:** são as restrições gerais pedidas para todos os papéis (sem promessa, sem pergunta repetida, sem afirmar o
que ninguém disse), mais as micro-alucinações vistas em outros papéis: prazo inventado, pedido de laudo e opinião
jurídica. O texto não tem "garant…", "100%" nem "você tem direito", para não acionar as travas de produção.

## 16. PASSO A: acolhimento curto sem promessa, "por quê?" respondido pelo resumo, advogado já explicado

**Problema visto:** (a) nenhuma saída para o lead que lamenta ("poxa, que pena"); o único acolhimento que ele recebia era
o do SDR na passagem, que fala de "se sua situação mudar no futuro". (b) Com a regra de DÚVIDAS ("responda e siga o
passo"), um "mas por quê?" logo depois da passagem levaria a explicar o motivo duas vezes (resposta + resumo), e a 2ª
explicação é onde nasce a opinião jurídica inventada. (c) sc12[atuando_hoje] 0317 T3/T4: o SDR já tinha explicado a
ética do advogado; o PASSO A mandava a mensagem da etapa 2 de novo, e só a etapa 2 dizia para pular.
**ANTES:** PASSO A sem acolhimento, sem regra para "por quê?" e com só uma exceção (o lead que diz que algo mudou).
**DEPOIS:** "Se o lead lamentou ("poxa", "que pena"), pode abrir com uma frase curta de acolhimento, sem promessa (ex.:
"Entendo, sei que não é a resposta que você esperava."). Se ele perguntou "por quê?", o próprio resumo responde, porque
o motivo está nele: não explique duas vezes. Exceções: … se o motivo for advogado e a conversa já explicou que não dá
para seguir por causa dele, vá para o PASSO B." Em DÚVIDAS, o item "Por quê?" ganhou "(no PASSO A, o resumo já
responde)".
**Por quê:** o modelo decide pelo bloco de PASSOS no topo; regra que só existe lá embaixo (etapa 2, DÚVIDAS) perde para
ele. O acolhimento tem exemplo pronto e sem futuro ("vai dar certo", "outro caminho"), que é o que as travas e o
escritório pedem.

---

## Conferência (script `conferir_desqualificado_motor.py`, no scratchpad da sessão)

Resultado: **OK, nenhuma falha.**
- Frase de troca do desqualificado citada 1x, idêntica à `mensagem_troca` do snapshot. As frases de periododegraca,
  closer e contratos não aparecem. `destinos` vazio e `boas_vindas` nula continuam iguais.
- Os 7 links do original aparecem o mesmo número de vezes, e não há link novo.
- Não há "garant…", "100%", "você tem direito" nem "você vai receber", e `catalogo.conferir` não barra o texto.
- As 11 mensagens fixas do escritório (etapas 2, 3, 4 e ENCERRAMENTO) estão idênticas. A confirmação é idêntica, só com
  a maiúscula inicial.
- Os 14 títulos do original estão presentes e na ordem. Há 2 títulos novos.
- O modelo do resumo não tem travessão, `;` nem "não tendo", e tem a vaga `[motivo real…]`. "não tendo" não aparece em
  lugar nenhum do prompt, a tabela MOTIVO REAL não tem prazo em número, e o PASSO A segura a nota e tem a saída do
  advogado já explicado. Os exemplos não têm colchetes, reticências, travessão nem ", ,", e os dados fictícios não
  aparecem em nenhum cenário.
- `ferramentas_do_prompt` não tira destino nem ferramenta do texto, e `montar_sistema` monta o sistema (18 mil
  caracteres). O prompt passou de 6,7 mil para 16,4 mil caracteres.

## O que o prompt sozinho não resolve

- **Balões:** `catalogo.separar_midias` junta itens de texto seguidos com "\n", e o `formatador` só divide em "\n\n" ou
  acima de 320 caracteres. "Balão 1 / Balão 2" pode chegar como um balão com quebra de linha. A ordem e o conteúdo ficam
  certos, mas a separação visual depende do motor.
- **Ano errado do extrator:** a regra 4 manda tirar a data da fala do lead, e não dos DADOS JÁ INFORMADOS. A raiz, porém,
  é o extrator converter "até hj" em `acidente_ano=2026` (analise_rodada2, classe motor).
- **Checagem:** nenhuma checagem do avaliador mede a ordem confirmação → resposta → nota (analise_rodada2, classe
  checagem). Este erro só aparece lendo a transcrição.
- **Não testado com o modelo:** a conferência é estática. Para medir, rode sc12[atuando_hoje], sc13 (2 variantes), sc15 (3),
  sc16 (2) e sc17[sem_documentos] com este prompt, de preferência 3 rodadas cada (gpt-4.1-mini, temperatura 0.5).


## Corretor, rodada 1 (2026-11-25)

Mudanças mínimas pedidas pela revisão. Frases de troca (mensagem_troca), links de mídia e dados do escritório intactos.

- **[14] A vaga [situação de trabalho…] não tinha regra para apagar.** Confirmado. O SDR desqualifica o aposentado (e quem já recebe auxílio-acidente) antes da pergunta da CLT, e o modelo preenchia a vaga com o que tinha à mão: "estando você aposentada desde 2021", ", ,".
  - DEPOIS, acrescentado ao item: "Se o lead não disse como trabalhava na data do acidente, apague "estando você…" inteiro, com a vírgula. Não deduza "carteira assinada" do local ou do trajeto ("indo pra confecção")."
- **[5] Saiu a linha do MOTIVO REAL "Já pediu esse benefício e ele foi negado".**
  - O SDR não desqualifica mais por pedido negado: o caso vira a OBJ 9, como nas outras etapas.
  - Sem a linha, um lead desqualificado por outro motivo que também contou um pedido negado não recebe o motivo errado.
  - Decisão do escritório a confirmar (ver MUDANCAS_sdr.md).
