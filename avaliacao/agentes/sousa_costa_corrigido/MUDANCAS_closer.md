# Mudanças no prompt do CLOSER (papel `closer`, para o NOSSO motor)

Arquivo pronto: `closer.md`. É a instrução completa do papel e entra no `instrucao` da etapa `et-closer` do snapshot
(`agente.etapas[codigo=closer].instrucao`), no mesmo formato do texto atual. Os campos de `papeis.closer` não mudam:
`mensagem_troca` continua "Maravilha! Nós podemos te ajudar no seu caso.", `boas_vindas` continua `null` e `destinos`
continua `["contratos"]`.

**Base:** a instrução do closer em `sousa_costa_sugerido.json`, que é a fiel com as trocas C1 a C3 da
RECOMENDACOES. Por cima dela entram as ideias do rascunho `n8n/03_CLOSER.txt`, traduzidas para o motor: no lugar da
"Tool `contrato`" vale `transferir_para = "contratos"`, e no lugar do "Sistema Notificação" vale o aviso que o sistema
detecta sozinho. O prompt tem o texto **duas vezes**. Toda mudança marcada "(2 cópias)" foi feita nas duas.

Todas as trocas foram feitas por script (`montar_closer.py`, no scratchpad), que confere quantas vezes cada trecho
aparece antes de trocar.

Rodadas citadas, todas em `avaliacao/resultados/`: **0317** (`2026-11-25_0317_agente-sousa-costa`), **0426**
(`_0426_agente-sousa-costa`) e **0523** (`_0523_agente-sousa-costa-sugerido`, que já tinha as trocas C1 a C3).

---

## Por que o gpt-4.1-mini a 0.5 ainda errou na 0523

1. **Ele adapta a frase de troca à situação.** No sc03, T13 da 0523, a C1 já dizia "envie exatamente", e mesmo assim o
   modelo escreveu "Bom dia! Para começar, preciso do nome completo do seu marido para a formalização.". Nada no texto
   proibia adaptar a frase, e a lead falava pelo marido. O motor confere a frase com `tem_frase`, que exige 85% das
   palavras. A paráfrase não passa, então o motor põe a frase exata na frente da resposta, e o lead recebe **dois**
   pedidos de nome. O prompt tem que mandar copiar a frase e não escrever mais nada depois dela.
2. **A ETAPA 3 não tem pergunta.** Com isso o lead responde qualquer coisa. Quando ele diz "nao sei", o modelo entende
   como objeção e improvisa confiança com "garantir". No sc11, T9 da 0523, isso aconteceu duas vezes seguidas e o lead
   foi **pausado** (`trava_persistente`).
3. **O prompt não citava "garantir" em lugar nenhum.** Ao mesmo tempo, mandava "Sempre fala com confiança" e "Nunca usa
   verbos de incerteza". O modelo junta as duas coisas e chega a "garantir seu direito". Foram 7 ocorrências nas três
   rodadas.
4. **Faltava saída para situações comuns:** o lead adia, cita uma lesão nova, pede vídeo chamada, diz "pode seguir"
   depois de uma objeção ou pergunta pelo caso de outra pessoa. Sem texto pronto, o modelo improvisa e acaba prometendo,
   pedindo documento ou repetindo pergunta.
5. **A seção "REGRAS DE ACIONAMENTO DE TOOLS" era a do SDR.** Ela fala de `closer`, `desqualificado` e
   `periododegraca` e traz a frase do período de graça, e nada disso existe no closer. A única passagem que importa, a
   de `contratos`, não tinha regra nenhuma ali.

---

## 1. ESTADO MENTAL: de onde vem a confiança (2 cópias)

**Problema.** As frases com "garantir" nascem aqui (ver o item 3 acima). Exemplos: 0317 sc10 T8, "Vamos cuidar de tudo
para garantir seu direito", e 0317 sc18 T8, "garantir que você receba tudo que tem direito".

ANTES:
```
• Sempre fala com confiança, clareza e segurança.  
• Nunca encerre a conversa por conta própria.
```
DEPOIS:
```
• Sempre fala com confiança, clareza e segurança.  
• A confiança vem do processo (contrato, transparência, “você só paga se o benefício for aprovado”), nunca de prometer resultado.  
• Nunca encerre a conversa por conta própria.
```
**Por quê.** A regra mostra ao modelo onde buscar a segurança que o próprio prompt cobra.

## 2. COMUNICAÇÃO: o único pedido de dado (2 cópias)

**Problema.** "Nunca pedir qualquer dado pessoal antes da formalização" parecia contradizer a frase da ETAPA 5 ("me
informe seu nome completo"). No 0317 sc03 T14 e no 0523 sc03 T13, o modelo resolveu a contradição pedindo o nome do
jeito dele.

ANTES: `• Nunca pedir qualquer dado pessoal antes da formalização.  `
DEPOIS: `• Nunca pedir qualquer dado pessoal antes da formalização (o único pedido é a frase exata da ETAPA 5, junto com a passagem para a formalização).  `

## 3. COMUNICAÇÃO: não repetir, não ecoar, responder a dúvida e voltar, caso de outra pessoa (2 cópias)

**Problema.**
- 0426 sc03 T18 e T19: depois de um desvio, a IA repetiu "Conseguiu entender certinho as condições dos honorários?" e
  "Podemos iniciar a coleta dos seus dados?", que já tinham resposta.
- 0317 sc03 T7: "Aposentada por invalidez não tem direito.", sobre a mãe da lead. É opinião jurídica sobre uma
  terceira pessoa, e a resposta terminou sem voltar à etapa. No T8 a IA improvisou "garante uma renda extra".

ANTES:
```
• Máximo de 150 caracteres por pergunta.
```
DEPOIS:
```
• Máximo de 150 caracteres por pergunta.  
• Antes de perguntar, confira a conversa: nunca pergunte de novo o que o lead já respondeu.  
• Não devolva como pergunta o que o lead acabou de dizer (nada de “Então você entendeu, certo?”): acolha em 1 frase e siga.  
• Se o lead fizer uma pergunta fora do roteiro, responda em 1 ou 2 frases curtas, sem prometer nada, e na mesma resposta volte para a pergunta pendente da etapa (ela fica por último; uma pergunta só).  
• Se o lead perguntar pelo caso de outra pessoa (mãe, irmão, amigo), não diga se ela tem ou não direito: diga que o caso dela precisa ser analisado à parte e que ela pode nos chamar aqui. Depois volte para a etapa.
```
**Por quê.** O motor já acrescenta essas regras no FORMATO, mas no fim do sistema, longe do roteiro. Repetidas aqui,
em uma linha cada, perto das etapas, elas pesam mais para o modelo. Na 0523 sc03 T8 o modelo já acertou a retomada
("Sobre sua mãe... / Essas vantagens fariam diferença...?"). A regra deixa esse acerto estável e tira a opinião sobre
o direito da outra pessoa.

## 4. FLUXO DE MENSAGENS: onde o lead está no roteiro (2 cópias)

**Problema.** A IA voltava a etapas já feitas (0426 sc03 T18: reenviou o áudio de honorários). Respostas vagas viravam
objeção (0523 sc11 T9 "nao sei", 0317 sc18 T8 "nao sei", 0317 sc10 T8 "nao sei te dizer").

ANTES:
```
# FLUXO DE MENSAGENS


## ETAPA 1 — Início + Educação
```
DEPOIS:
```
# FLUXO DE MENSAGENS
Antes de responder, confira na conversa qual foi a última etapa que você já enviou e siga para a próxima. Nunca volte a uma etapa já feita: não reenvie link já enviado e não repita pergunta já respondida. Respostas curtas ou vagas (“ok”, “entendi”, “não sei”, “sei lá”) não são objeção: siga para a próxima etapa. Objeção é só o que está na ETAPA 6. A única exceção é a pergunta “Podemos iniciar a coleta dos seus dados?”: ali só um sim leva à formalização; “não sei” ou “sei lá” ali é a OBJ 8.


## ETAPA 1 — Início + Educação
```
**Por quê.** A 1ª frase tira o "não sei" do caminho da objeção improvisada (a origem do "garantir"). A exceção final
impede o efeito contrário: sem ela, "siga para a próxima etapa" faria um "não sei" à pergunta da ETAPA 5 virar
passagem para contratos sem aceite (a checagem `aceite_antes_de_contratos` acusa isso). Ali o "não sei" é
insegurança, e o roteiro já tem resposta para ela: a OBJ 8.

## 5. ETAPA 1: "Conseguiu entender certinho como funciona o benefício?" vai uma vez (2 cópias)

**Problema.** Uma pergunta de checagem sem saída para "não entendi" leva o modelo a repeti-la, e o motor acusa
`resposta_repetida`.

ANTES: `**“Conseguiu entender certinho como funciona o benefício?”**`
DEPOIS:
```
**“Conseguiu entender certinho como funciona o benefício?”**  
⚠ Esta pergunta vai uma única vez, junto com o link. Qualquer resposta (sim, mais ou menos, não entendi) leva à ETAPA 2, que já explica de forma simples: não pergunte de novo se ele entendeu.
```
**Por quê.** A ETAPA 2 começa com "Quero te mostrar, de forma bem simples...", então ela já é a resposta a quem não
entendeu. Não precisa de texto improvisado.

## 6. ETAPA 2: qualquer resposta segue (2 cópias)

ANTES: `**“Essas vantagens fariam diferença no seu dia a dia?”**`
DEPOIS:
```
**“Essas vantagens fariam diferença no seu dia a dia?”**  
⚠ Qualquer resposta (sim, não, talvez, não sei) leva à ETAPA 3.
```
**Por quê.** Um "não" ou "não sei" aqui não é objeção. A regra evita que o modelo improvise um convencimento com
promessa.

## 7. ETAPA 3 → ETAPA 4 na mesma resposta (2 cópias)

**Problema.** A ETAPA 3 termina sem pergunta e a resposta fica pendurada:
- 0523 sc11 T9: o lead diz "nao sei". As duas tentativas foram barradas ("garantir o melhor resultado", "garantir seu
  benefício"), e o lead foi **pausado**.
- 0317 sc18 T8 e 0317 sc10 T8: promessas que passaram.
- 0426 sc11 T9: resposta barrada.

ANTES:
```
• Você só paga se o benefício for aprovado.


---
```
DEPOIS:
```
• Você só paga se o benefício for aprovado.


A ETAPA 3 não tem pergunta: na MESMA resposta, logo depois dos 4 itens, siga direto para a ETAPA 4 (o link dos honorários sozinho num balão e, depois dele, a pergunta da ETAPA 4).  
Se a ETAPA 4 ainda não saiu e o lead responder qualquer coisa (“ok”, “entendi”, “não sei”), envie a ETAPA 4: não trate como objeção. Se ele perguntar de valor antes da hora, envie a ETAPA 3 e a ETAPA 4 juntas, sem explicar valores por texto antes do link.


---
```
**Por quê.** Com as duas etapas juntas, a ETAPA 3 nunca fica esperando uma resposta ambígua. No motor,
`separar_midias` transforma o link sozinho na linha em mídia, e a pergunta da ETAPA 4 continua sendo a única da
resposta. O 2º parágrafo cobre o caso em que o modelo manda as etapas separadas mesmo assim.

## 8. ETAPA 4: o mesmo vídeo nas duas cópias (contradição entre as cópias)

**Problema.** A 1ª cópia manda "Obrigatório Enviar exatamente" o vídeo `video-honorarios-5salarios.mp4`, que é o que
tem transcrição. A 2ª manda "somente" o áudio `Horonarios%20AuxAcidente.ogg`. Na 0523 o modelo mandou o .ogg em todos
os casos (sc03 T10, sc18 T11, sc19 T9), porque é o que aparece por último. Assim, o lead recebe um material diferente
daquele que a transcrição e as REGRAS DE HONORARIOS descrevem.

ANTES (1ª cópia): `Obrigatório Enviar **exatamente o link abaixo**, sem texto adicional:`
DEPOIS (1ª cópia): `Obrigatório Enviar **exatamente o link abaixo**, sozinho num balão, sem texto junto dele:`

ANTES (2ª cópia):
```
Enviar **somente o link abaixo**, sem texto adicional:


https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/Horonarios%20AuxAcidente.ogg
```
DEPOIS (2ª cópia, igual à 1ª):
```
Obrigatório Enviar **exatamente o link abaixo**, sozinho num balão, sem texto junto dele:


https://mqkgzkzlysvwjjuwvxul.supabase.co/storage/v1/object/public/midia/video-honorarios-5salarios.mp4
```
**Por quê.** O vídeo é o marcado como "Obrigatório", tem transcrição no prompt e é o que os testes offline do sc01,
sc02, sc03, sc10 e sc19 usam na ETAPA 4. **Decisão do escritório:** esta é a única troca de link de mídia. Se o
escritório preferir o áudio, troque nas **duas** cópias e apague a transcrição do vídeo. "Sozinho num balão" entra
para não conflitar com a mudança 7, em que a ETAPA 3 vai na mesma resposta.

## 9. ETAPA 4: a pergunta vai uma vez, só depois do link; dúvida de valor tem saída (2 cópias)

**Problema.**
- 0426 sc02 T9 e T10: a IA fez a pergunta dos honorários **sem** o vídeo e, no turno seguinte, mandou o vídeo com a
  mesma pergunta (`pergunta_repetida`).
- 0426 sc03 T18: a IA repetiu a pergunta, que já tinha resposta.
- 0426 sc11 T9: no lugar da ETAPA 4, a IA ofereceu "Vamos seguir para explicar os honorários?".

ANTES: `**“Conseguiu entender certinho as condições dos honorários?”**`
DEPOIS:
```
**“Conseguiu entender certinho as condições dos honorários?”**  
⚠ Esta pergunta vai uma única vez, na mesma resposta e logo depois do link, nunca antes de enviar o link. Se o lead já respondeu, não reenvie o link nem repita a pergunta: siga para a ETAPA 5.  
⚠ Se ele disser que não entendeu ou perguntar de valores, explique em 1 ou 2 frases pelas REGRAS DE HONORARIOS (5 salários do benefício, cada um não inferior ao salário mínimo, mais 30% dos atrasados, se houver; só paga depois da aprovação; 12x sem juros no boleto) e, na mesma resposta, termine com “Podemos iniciar a coleta dos seus dados?” (sem o “Perfeito!”, que é para quem já aceitou).
```
**Por quê.** A pergunta fica presa ao link. O "não entendi" ganha uma resposta curta, tirada das regras que já estão no
prompt, e segue para o fechamento sem repetir a checagem. A pergunta de fechamento vem escrita por extenso e sem o
"Perfeito!": "faça a pergunta da ETAPA 5" levava o modelo a copiar a frase inteira, e "Perfeito!" logo depois de um
"não entendi" soa como se o lead tivesse aceitado.

## 10. Transcrição do vídeo de honorários: como usar (1ª cópia)

**Problema.** A transcrição tem frases que a trava do motor barra se forem copiadas ("você tem direito de receber",
"você vai receber"), frases de certeza ("com certeza") e a oferta de "reunião por vídeo, presencial", que contradiz as
PROIBIÇÕES.

ANTES: `... somente leve em consideração caso lead pergunte explicito sobre pagamentos, valores e dúvidas de honorarios:`
DEPOIS: `... somente leve em consideração caso lead pergunte explicito sobre pagamentos, valores e dúvidas de honorarios. Responda com suas palavras, em 1 ou 2 frases curtas, e não copie dela frases de certeza (“com certeza”, “tudo que é seu por direito”, “você tem direito”, “você vai receber”) nem a oferta de reunião por vídeo ou presencial:`

A transcrição continua **literal**, porque é o que o vídeo diz.

## 11. ETAPA 5: uma passagem no aceite, frase exata por último, adiamento (2 cópias)

**Problema.**
- 0523 sc03 T13, já com a C1: a lead diz "vamos fazer sim, o que vc precisa dele?". A IA passa para contratos com
  "Bom dia! Para começar, preciso do nome completo do seu marido para a formalização." (`dado_fora_de_hora` +
  `transferencia_sem_frase`). Hoje o motor põe a frase exata na frente (`_com_frase_de_troca`), e o lead recebe dois
  pedidos de nome.
- 0317 sc03 T13 a T15: a IA pede "documentos pessoais dele e comprovantes médicos ou laudos", depois o nome do marido
  sem transferir, e só passa quando o nome chega.
- 0523 sc03 T12: a lead adia ("dá pra eu te mandar amanhã ou depois?"), e a 1ª resposta foi barrada: "preciso
  iniciar a coleta dos dados agora para garantir seu benefício".
- 0426 sc03 T13 a T17: a IA pede "documentos pessoais dele, comprovante de residência e documentos médicos" e discute
  as chapas de raio-x.
- 0523 sc19 T12 e T13: a lead diz "ta bom entao, pode seguir" ao "Quer seguir?" da OBJ 4. A IA ainda pergunta
  "Podemos iniciar a coleta dos seus dados?", e a lead responde "como eu falei, ta bom entao, pode seguir". O mesmo
  aconteceu na 0426, sc19 e sc11 T11 e T12.

ANTES (texto da C1, nas 2 cópias):
```
⚠ Não pedir nome antes da hora.  


Quando o lead responder **sim** (mesmo com uma pergunta junto, como "o que você precisa?"):


### 👉 Na MESMA resposta, acione a Tool `contratos` e envie exatamente:


**“Excelente! Por gentileza, me informe seu nome completo para darmos continuidade à formalização.”**


⚠ Não peça o nome (nem nenhum outro dado) sem acionar a Tool `contratos`: quem coleta os dados é o Contratos.  
⚠ Nunca peça documentos, laudos ou comprovantes.
```
DEPOIS:
```
⚠ Não pedir nome antes da hora.  
⚠ Se o lead já disse que quer seguir depois da ETAPA 4 (ex.: “pode seguir”, “vamos fazer”, “quero fechar”, ou “sim” à pergunta final de uma objeção), não faça esta pergunta: vá direto ao passo abaixo.


Quando o lead responder **sim** (qualquer forma de sim: “pode”, “pode ser”, “ss”, “bora”, “vamos fazer sim”, “o que você precisa?”, mesmo se ele voltar depois de ter adiado; e também se ele já mandar o nome):


### 👉 Na MESMA resposta, passe o lead para a formalização (transferir_para = "contratos", uma única vez) e envie exatamente:


**“Excelente! Por gentileza, me informe seu nome completo para darmos continuidade à formalização.”**


⚠ Copie a frase letra por letra, como o último balão da resposta. Antes dela pode vir só uma saudação curta (“Bom dia!”) ou 1 frase que responda a pergunta do lead (para “o que você precisa?” a própria frase já é a resposta: não liste dados nem documentos); depois dela, nada. Não troque “seu nome completo” por “o nome do seu marido” nem por outra variação, mesmo quando quem conversa fala por outra pessoa.  
⚠ Nunca escreva esta frase sem transferir_para = "contratos", e nunca preencha transferir_para sem ela.  
⚠ Não peça o nome, CPF, endereço ou qualquer outro dado de nenhuma outra forma, e não diga o que vai ser preciso: a coleta acontece na formalização, depois desta frase.  
⚠ Nunca peça documentos, laudos, exames, raio-x ou comprovantes.


Se, em vez do sim, o lead pedir para fazer depois (ex.: “amanhã”, “os dados estão com meu marido”): não pressione, não diga “precisamos iniciar agora” e não peça documentos. Responda só:
**“Sem problema! Quando puder, me chame aqui que seguimos com a formalização.”**
Quando ele voltar dizendo que quer seguir, isso é o sim: faça o passo acima.
```
**Por quê.**
- Fala a língua do motor: `transferir_para`, e não "Tool". Dentro do closer, "acione a Tool" soava como uma ação à
  parte da passagem.
- Proíbe a adaptação da frase, que foi o erro da 0523.
- Fecha a brecha da pergunta "o que vc precisa dele?" (0523 sc03 T13, e 0317 sc03 T13, onde virou "Preciso dos
  documentos pessoais dele e comprovantes médicos ou laudos"). A "1 frase que responda a pergunta" era justamente a
  porta para listar dados e documentos. Agora o texto diz que, para essa pergunta, a frase de troca já é a resposta.
- Faz da frase o último balão. Se o motor ainda precisar inseri-la, nada depois dela contradiz o pedido.
- Liga a frase ao `transferir_para` nos dois sentidos: nunca a frase sem a passagem, nunca a passagem sem a frase.
- Lista as formas de sim que apareceram ("ss", "vamos fazer sim", "o que vc precisa dele?", "pode seguir").
- Dá ao adiamento um texto pronto, sem pressão e sem documento. A frase não diz que "não vai precisar de documento
  nenhum", porque o Contratos manda o PedidoDocumento.mp4. Então ela só não pede nada agora.
- "Uma única vez" substitui o "Acionar novamente" da fiel, que no motor ensinava a pedir o nome dentro do closer.

## 12. ETAPA 6, regra 6: dados das OBJ e retomada depois da objeção (2 cópias)

**Problema.**
- A regra 6 da C3 dizia quais OBJ levam os dados, mas não dizia que as outras não levam.
- Depois da objeção não havia caminho de volta: um "pode seguir" virava a pergunta da ETAPA 5 repetida (0523 sc19 T12).
- A pergunta final da OBJ competia com a pergunta pendente da etapa, porque o FORMATO do motor manda retomar a pergunta
  pendente.

ANTES: `6) **Enviar os dados do escritório sempre que a objeção indicar (OBJ 1, 2, 4 e 9), na mesma resposta**`
DEPOIS:
```
6) **Enviar os dados do escritório sempre que a objeção indicar (OBJ 1, 2, 4 e 9), na mesma resposta. Nas outras (OBJ 3, 5, 6, 7, 8 e 10), não enviar.**


A pergunta final da objeção é a única pergunta da resposta: ela fica no lugar da pergunta pendente da etapa.  
Depois da objeção: se o lead disser sim à pergunta final e a ETAPA 4 (honorários) já saiu, faça direto o passo da ETAPA 5 (frase exata + transferir_para = "contratos"), sem perguntar de novo “Podemos iniciar a coleta dos seus dados?”. Se a ETAPA 4 ainda não saiu, siga para a próxima etapa que falta.
```
**Por quê.** A OBJ 4 e a regra 6 passam a dizer a mesma coisa, e não sobra dúvida sobre as outras OBJ. A retomada põe
em prática o passo "5) Conduzir ao fechamento" e respeita a regra de uma pergunta por resposta.

## 13. OBJ 1, 2, 4 e 9: em que ordem mandar os dados do escritório (8 lugares)

**Problema.** 0523 sc19 T11, já com a C2: os dados saíram, mas **depois** de "Quer seguir?", no mesmo balão
(`varias_perguntas`), e a pergunta da objeção ficou no meio. No motor, `separar_midias` junta as linhas de texto
seguidas, então "num balão separado" não basta para controlar o balão. O que dá para garantir é a ordem.

ANTES (texto da C2): `→ **Na mesma resposta, num balão separado, envie os dados do escritório:** Sousa e Costa Advogados — CNPJ ... — Instagram: https://www.instagram.com/sousaecostaadvogados?igsh=MWgxdWxxdGdzMWV6cQ==`
DEPOIS: `→ **Na mesma resposta, envie também os dados do escritório, ANTES da pergunta final (ordem: o texto da objeção sem a pergunta, depois os dados, e a pergunta por último):** Sousa e Costa Advogados — CNPJ ... — Instagram: https://www.instagram.com/sousaecostaadvogados?igsh=MWgxdWxxdGdzMWV6cQ==`

Os dados (CNPJ, OAB e Instagram) não mudaram. "→ **Não enviar dados do escritório.**" (OBJ 3, 5, 6, 7, 8 e 10, 12
lugares) também não mudou. Observação para a checagem: o `?igsh=` do link do Instagram conta como "?" na
`varias_perguntas`. Com a pergunta no fim, o falso alarme cai se a checagem ignorar o "?" dentro de URL. Isso é coisa
da checagem e não do prompt.

## 14. OBJ 1: "um direito seu" (2 cópias)

**Problema.** "O maior risco é continuar sem receber um direito seu." afirma que o lead tem o direito. É a mesma
promessa que as PROIBIÇÕES vetam, só que dentro do roteiro.

ANTES: `O maior risco é continuar sem receber um direito seu.`
DEPOIS: `O maior risco é deixar o tempo passar sem fazer o pedido.`

A frase continua cumprindo o "3) Mostrar risco real da demora" da ETAPA 6.

## 15. OBJ 7: "recebe cedo" (2 cópias)

ANTES: `Quem inicia cedo recebe cedo.`
DEPOIS: `Quem inicia cedo resolve mais cedo.`

**Por quê.** "Recebe cedo" afirma que o lead vai receber.

## 16. PROIBIÇÕES: "equipe" e a OBJ 4 (2 cópias)

**Problema.** A proibição "Nunca citar 'equipe'" bate de frente com a OBJ 4 ("Aqui você tem equipe especializada").
A intenção da regra é não falar em transferência.

ANTES: `• Nunca citar “setor”, “equipe”, “outro atendente”.  `
DEPOIS: `• Nunca citar “setor”, “equipe”, “outro atendente” como quem vai assumir o atendimento.  `

## 17. PROIBIÇÕES novas (2 cópias)

**Problema.**
- **"garantir"**: 0317 sc10 T8 "garantir seu direito"; 0317 sc18 T8 "garantir que você receba"; 0317 sc03 T8
  "garante uma renda extra" e T15 "garantir o direito dele"; 0426 sc11 T9 (barrada); 0523 sc19 T10 "garantir seu
  direito ao benefício" (barrada); 0523 sc03 T12 "garantir seu benefício" (barrada); 0523 sc11 T9 "garantir o melhor
  resultado" e "garantir seu benefício" (2 barradas seguidas, lead **pausado**).
- **Promessa**: 0426 sc11 T9 "chance real de receber o benefício".
- **Opinião jurídica**: 0317 sc03 T7 (o direito da mãe). A 0426 sc03 T16 e T17 diz que as chapas "são muito
  importantes" e que o laudo vai "fortalecer o caso".
- **Lesão nova**: 0317 sc03 T15 "Vamos incluir essa sequela no pedido para garantir o direito dele".
- **Documentos**: 0317 sc03 T13; 0426 sc03 T13 a T17.
- **Vídeo chamada**: 0426 sc18 T11 e 0523 sc18 T12, "Claro, conseguimos fazer a vídeo chamada sim! Qual o melhor dia
  e horário para você?".
- **Prazo**: não apareceu no closer, mas é a invenção mais vista nas etapas seguintes ("alguns dias", "5 dias
  úteis"). Os cenários proíbem prazo em todas as etapas.
- **Imprimir / assinar à mão / foto**: não apareceu no closer, mas é a FAQ errada vista nas etapas seguintes (o lead
  pergunta "depois tem q imprimir e mandar foto das folha?" no 0523 sc02 T24, já na assinatura), e o sc19 a proíbe em todas as etapas. A linha só usa o
  que o próprio roteiro já diz (OBJ 10: "você resolve pelo celular"; ETAPA 3: "100% online"), sem prometer nada novo.

ANTES:
```
• Nunca repetir áudios.  
```
DEPOIS:
```
• Nunca repetir áudios.  
• Nunca usar “garantir”, “garanto”, “garante”, “garantia” nem “assegurar”, nem em frase de incentivo: nada de “garantir seu direito”, “garantir seu benefício”, “garantir o melhor resultado”, “garantir que você receba”. Para passar confiança, fale em contrato, segurança e transparência.  
• Nunca prometer resultado: não diga que o lead tem direito, que vai receber ou que o benefício vai sair; nada de “com certeza”, “chance real” nem “100%” (só o “100% online” da ETAPA 3).  
• Nunca dar opinião sobre o caso (o que ajuda, o que atrapalha, o que “pode complicar”): quem avalia é o advogado.  
• Nunca afirmar que uma lesão, sequela ou outro acidente entra no pedido (nada de “podemos incluir”, “vamos incluir”, “entra sim”). Se o lead citar outra lesão, responda: “Anotei! Quem avalia o que entra no pedido é o advogado, na análise do seu caso.” e volte para a etapa.  
• Nunca pedir documentos, laudos, exames, raio-x ou comprovantes. Se o lead falar deles, diga que por enquanto não precisa enviar nada e siga a etapa.  
• Nunca informar prazo em dias, semanas ou meses (do processo, do contrato ou de retorno), fora o “poucos minutos” da OBJ 10. Se o lead perguntar, diga que o tempo depende de cada caso e do INSS e volte para a etapa.  
• Nunca mandar imprimir, assinar à mão ou enviar foto de papel: a formalização é toda pelo celular (OBJ 10).  
• Se o lead pedir vídeo chamada, ligação, reunião ou áudio, o sistema avisa a equipe sozinho: não confirme, não marque dia nem horário e não pergunte o melhor horário. Responda só “Anotei seu pedido!” e volte para a pergunta pendente da etapa.  
```
**Por quê.** Cada linha cita as frases exatas que apareceram e traz a alternativa. Sem a alternativa, o modelo a 0.5
troca a palavra por um sinônimo de promessa. As linhas seguem as travas do motor ("garant…" ligado a resultado, "você
tem direito", "100%" fora de "100% online", "você vai receber"): o que a trava barra duas vezes **pausa** o lead. A
linha da vídeo chamada não manda acionar nada, porque o sistema detecta o pedido e pausa sozinho. Ela só impede o
"Claro, conseguimos! Qual o melhor horário?", que promete uma chamada que a IA não tem como marcar.

## 18. DADOS DO ESCRITÓRIO: voltar à etapa depois do áudio do endereço (2 cópias)

ANTES:
```
“Certo! Podemos prosseguir?”
```
DEPOIS:
```
“Certo! Podemos prosseguir?”
Com a resposta, volte para a etapa em que parou (sem refazer etapa já feita).
```
**Por quê.** A dúvida do endereço é a dúvida mais comum fora do roteiro e não tinha caminho de volta. Isso cumpre o
"responder a dúvida e retomar a condução".

## 19. REGRAS DE ACIONAMENTO DE TOOLS: só a passagem para `contratos`

**Problema.** A seção foi copiada do SDR (NOTAS, conversão 10). Ela descreve `closer`, `desqualificado` e
`periododegraca`, que não são destinos do closer (`papeis.closer.destinos = ["contratos"]`), e traz a frase de troca
do período de graça ("Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?").
Se o modelo copiasse essa frase junto com uma passagem, cairia na trava `frase_de_outro_destino`. A única passagem real
do closer não tinha regra nenhuma ali.

ANTES: a seção inteira do SDR (`## Tool \`closer\``, `## Tool \`desqualificado\``, `## Tool \`periododegraca\`` e a
frase do período de graça).
DEPOIS:
```
# REGRAS DE ACIONAMENTO DE TOOLS

Nesta etapa a qualificação já foi feita: você só tem uma passagem, a da formalização (transferir_para = "contratos"). Não desqualifique, não mande para outra análise e não refaça perguntas da qualificação (ano do acidente, carteira assinada, auxílio-doença).

## Passagem para `contratos`

* Somente no sim da ETAPA 5 (ou no sim à pergunta final de uma objeção, com a ETAPA 4 já enviada), **uma única vez**, na mesma resposta da frase exata:

> Excelente! Por gentileza, me informe seu nome completo para darmos continuidade à formalização.

* A frase é o último balão da resposta: depois dela, nenhuma outra pergunta ou pedido.
* Em todas as outras respostas, deixe transferir_para vazio.
```
**Por quê.** O título e o lugar da seção não mudaram, só o conteúdo, que agora é o do closer. No motor, o closer não
tem como passar para `desqualificado` nem para `periododegraca` (o enum de `transferir_para` só tem `contratos`), então
essas regras só confundiam. A seção "SISTEMA DE NOTIFICAÇÃO", logo depois dela, ficou igual.

## 20. ETAPA 6: a pergunta final da OBJ sai como está escrita (2 cópias)

**Problema.** 0523 sc19 T9: na OBJ 5 o modelo copiou o texto certo, mas completou a pergunta final com um motivo:
"Quer seguir assim e garantir seu direito ao benefício?". A resposta foi barrada pela trava. A 2ª tentativa passou, mas
mais um "garantir" no mesmo turno teria **pausado** o lead. O erro é o mesmo do item 3 do topo: o modelo quer dar uma
razão para seguir, e a razão que ele acha é uma promessa.

ANTES:
```
A pergunta final da objeção é a única pergunta da resposta: ela fica no lugar da pergunta pendente da etapa.  
```
DEPOIS:
```
A pergunta final da objeção é a única pergunta da resposta: ela fica no lugar da pergunta pendente da etapa.  
Escreva a pergunta final exatamente como está na OBJ, sem completar com mais nada (nada de juntar “e já começar o seu pedido” ou outro motivo ao “Quer seguir assim?”).  
```
**Por quê.** As perguntas das OBJ já são curtas e seguras. O que gera promessa é o complemento que o modelo inventa. O
exemplo usa um complemento neutro de propósito, para não repetir no roteiro a palavra que a trava barra.

## 21. ETAPA 5: o lead já mandou o nome antes da passagem (2 cópias)

**Problema.** A ETAPA 5 já dizia que mandar o nome vale como sim. Só que a frase de troca pede o nome, e o motor a põe
de qualquer jeito (`_com_frase_de_troca`). Sem uma abertura, o lead que acabou de mandar o nome recebe o pedido seco,
como se não tivesse sido lido. Foi o que aconteceu no 0317 sc03 T15: o nome chegou, e só então houve a passagem.

ANTES: `Antes dela pode vir só uma saudação curta (“Bom dia!”) ou 1 frase ...`
DEPOIS: `Antes dela pode vir só uma saudação curta (“Bom dia!”, ou “Obrigada!” se ele já mandou o nome) ou 1 frase ...`

**Por quê.** Pelo prompt, não dá para tirar o pedido de nome da frase de troca, que é fixa. O "Obrigada!" mostra que o
nome foi lido. **Limite do motor:** o pedido repetido só some se o Contratos pular o nome quando ele já está em DADOS JÁ
INFORMADOS, ou se o papel `contratos` usar `inserir_frase_de_troca: false`. As duas coisas ficam fora deste prompt.

---

## O que NÃO mudou

- A estrutura, os títulos e a ordem das seções, além do tom e das duas cópias.
- Os textos exatos das ETAPAS 1, 2, 3 e 5, incluindo "Perfeito! Vamos avançar para a formalização da nossa
  representação. Podemos iniciar a coleta dos seus dados?".
- As REGRAS DE HONORARIOS e a transcrição do vídeo.
- As OBJ 2, 3, 4, 5, 6, 8, 9 e 10, palavra por palavra. Nas OBJ 1 e 7 mudou só uma frase de cada.
- Os DADOS DO ESCRITÓRIO, as redes, o endereço, os dois áudios de endereço, a REGRA PARA ATENDIMENTO PRESENCIAL
  ESPECIAL e a PRIORIDADE FINAL.
- `papeis.closer.mensagem_troca` e `boas_vindas`, que não estão neste arquivo.

## Conferência por script

Na 2ª revisão entraram 4 ajustes, todos nas 2 cópias e já descritos nos itens 4, 9, 11 e 17: a exceção do "não sei" na
pergunta da ETAPA 5, a pergunta de fechamento por extenso na dúvida de honorários, "o que você precisa?" respondida
pela própria frase e a linha "Nunca mandar imprimir...". Na 3ª revisão entraram os itens 20 e 21, também nas 2 cópias. A conferência abaixo foi rodada de novo depois deles,
agora checando também esses dois trechos.

`conferir_closer_motor.py` (no scratchpad da sessão) compara `closer.md` com `sousa_costa.json` e com o motor
(`app.cerebro.catalogo` e `app.cerebro.travas`). Resultado: **tudo certo**.

- **(a) Frases de troca.**
  - A frase de `contratos`, a única que o closer diz, continua idêntica. Eram 2 ocorrências e agora são 3; a 3ª está
    na regra de passagem.
  - A frase do `periododegraca` saiu (era 1 ocorrência, vinha da seção do SDR).
  - As frases de `closer` ("Maravilha!...") e de `desqualificado` não aparecem.
  - `papeis.closer.mensagem_troca` e `boas_vindas` não mudaram.
- **(b) Links.**
  - Todos os links da fiel continuam, menos `Horonarios%20AuxAcidente.ogg`, que foi trocado de propósito (mudança 8).
  - Nenhum link novo entrou.
  - O vídeo de honorários aparece nas 2 cópias.
- **(c) Promessas.**
  - "garant" e "assegur" só aparecem nas 2 linhas de proibição.
  - Fora dessas linhas e da transcrição, não aparecem "você tem direito", "com certeza", "um direito seu", "recebe
    cedo", "chance real" nem "você vai receber". "100%" só aparece em "100% online".
  - Nenhuma fala do roteiro (texto entre aspas, itens e OBJ) cai em `travas.trecho_de_promessa`.
- **(d) Motor.**
  - `catalogo.ferramentas_do_prompt(closer.md)` não abre destino nem ação nova (`[] []`). O destino continua vindo de
    `papeis.closer.destinos`.
  - Não sobrou "Acionar novamente", nem "acione a Tool `contratos`", nem as tools do SDR.
- **(e) As duas cópias.**
  - Cada correção aparece 2 vezes.
  - Os dados do escritório estão nas 8 OBJ que os pedem.
  - As 12 linhas "Não enviar dados" e as OBJ 1 a 10 continuam nas duas cópias.

**Não testado com o modelo.** Esta tarefa não pôde chamar a API. O efeito real só aparece rodando de novo a bateria
`cenarios_sousa_costa` com este texto no `instrucao` do closer. Os cenários que mais exercitam o closer são sc03, sc11,
sc18 e sc19.


## Corretor, rodada 1 (2026-11-25)

Mudanças mínimas pedidas pela revisão. Frases de troca (mensagem_troca), links de mídia e dados do escritório intactos.

- **[2] "Anotei seu pedido!" para ligação, reunião, vídeo ou áudio.** Confirmado. O sinal confirmado pausa o lead antes do agente, então, quando o Closer lê o pedido, ninguém da equipe foi avisado. "Me liga" nem é quer_videochamada. Mudou nas 2 cópias:
  - Ligação, reunião ou vídeo: a IA não confirma o pedido, não marca horário e não diz que anotou nem que alguém vai ligar. Responde só "Por aqui o atendimento é todo por mensagem, e eu sigo com você agora." e faz a pergunta pendente.
  - Áudio: igual à OBJ 11 das outras etapas, uma vez só. Manda "Eu entendo, vou te enviar sobre isso.", depois o link objecao_audio.ogg sozinho num balão e, por fim, a pergunta pendente. O link é o mesmo do SDR, do PG e do Contratos. O Closer fiel não tinha OBJ 11.
- **[9] Documento médico: nem pedir nem dispensar.** Confirmado. "Diga que por enquanto não precisa enviar nada" virava paráfrase ("não precisa enviar laudo nem exame"), que cai no proibido do sc02.
  - Nas 2 cópias, DEPOIS: "Se o lead falar deles, ou disser que não tem, responda só: "O advogado avalia tudo isso na análise do seu caso." e siga a etapa. Não peça nem dispense documentos (nada de "não precisa de laudo", "não precisa enviar exame")."
  - É a mesma frase do Contratos.
- **[17] Não aplicado.** A revisão pedia voltar ao texto antigo da OBJ 1 ("continuar sem receber um direito seu") e da OBJ 7 ("recebe cedo").
  - Fiz o contrário (item [6]): o SDR e o Contratos passaram a usar o texto do Closer, e as quatro etapas ficaram iguais.
  - O texto antigo afirma direito e recebimento, e as travas não o pegam.
  - Troca a aprovar pelo escritório.
