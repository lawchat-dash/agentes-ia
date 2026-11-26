# Mudanças na instrução do papel `assinatura` (nosso motor)

Arquivo novo: `assinatura.md`. É a instrução completa do papel e entra no lugar de
`agente.etapas[codigo="assinatura"].instrucao` do snapshot `sousa_costa.json`. A config do papel em
`config.catalogo.papeis.assinatura` não mudou: `mensagem_troca` e `boas_vindas` são `null`, `destinos` é `[]`,
`acoes` é `[]` e `notificacao` é `true`.

Ponto de partida:
- a instrução fiel (`sousa_costa.json`);
- a troca A1 do `sousa_costa_sugerido.json`, a única que o sugerido fez neste papel;
- as ideias do rascunho n8n (`n8n/05_ASSINATURA.txt`), convertidas para o motor. O motor não tem tool `Sistema
  Notificação`: o agente só preenche `"notificacao": "analise_humana"`, e os outros avisos o extrator marca sozinho.

Evidência usada:
- 0426 (fiel): sc01 T23–T32, sc02 T25–T26, sc03 T26, sc10 T22, sc11 T24;
- 0523 (sugerido): sc01 T23–T32, sc02 T24–T26, sc03 T26;
- código do motor: `catalogo.FORMATO` e `FORMATO_NOTIFICACAO`, `turno.py` (`diz_que_assinou`, `notificacao`),
  `pipeline.py` (`reenviar_link`, `verificar_assinatura`), `acoes.py` e `contrato/dados.py` (textos `pos_assinatura`,
  `pendente` e `mesmo_link`).

O `analise_rodada2.json` não tem nenhum achado com etapa `assinatura`.

## Por que o gpt-4.1-mini a 0.5 ainda errou com a 1ª leva

1. **O único caminho para sair estava em "continue ajudando normalmente".** No código, o prompt fiel diz que "o
   sistema percebe sozinho" e manda "continuar ajudando normalmente". Mas o extrator não marcou
   `dificuldade_assinatura` em nenhum turno da sc01 (nem na 0426, nem na 0523). O modelo ficou sem saída e continuou
   "ajudando" com a pergunta de sempre: "conseguiu abrir o link?" / "já olhou o spam?". Faltava uma escada com fim
   e um gatilho que o próprio agente acione (`analise_humana`, que o motor já aceita).
2. **Regra sem número não segura o modelo.** "Que você não consegue resolver depois de orientar" não diz quantas
   orientações dar. "Nunca repita a mesma mensagem" também falha, porque a cada vez o modelo troca as palavras.
3. **Faltava resposta pronta para prazo e para "já assinei".** Sem texto, o modelo improvisou "alguns meses",
   "alguns dias", "garantir o melhor resultado" e "Já confirmei aqui e o sistema também mostra".
4. **O fim de cada resposta virava pergunta.** O FORMATO manda "retomar a pergunta pendente da etapa", mas a
   Assinatura não tinha nenhuma pergunta pendente definida. O modelo inventava uma ("Posso ajudar com mais alguma
   dúvida?", "Conseguiu abrir o link?"), e isso alimentava o laço.
5. **Seção copiada do SDR.** A seção mandava passar para `closer`, `desqualificado` e `periododegraca` e "enviar o
   seguinte texto". Neste papel `transferir_para` só aceita vazio. É o mesmo padrão do problema geral: mandar dizer a
   frase de troca sem transferir.

---

## 1. FAQ de imprimir (A1)

**Problema:** 0426 sc02 T25: "Para assinar o contrato, é necessário imprimir todas as páginas, assinar e depois enviar a
foto para nossa equipe" (mesmo erro do chat real 2). Na 0523, já com a A1, a sc02 T24 respondeu certo.

ANTES:
```
-Preciso imprimir todas as folhas? → “Sim, é necessário imprimir todas as páginas, assinar e depois enviar a foto para nossa equipe.”
```
DEPOIS:
```
-Preciso imprimir todas as folhas? → “Não precisa imprimir nada: a assinatura é feita pelo celular, no próprio link que você recebeu.”
```
**Por quê:** a assinatura é digital (ZapSign). A frase casa com o `obrigatorio_em.assinatura` do sc02.

## 2. Regra geral: assinatura digital, contrato já gerado, link pelo sistema (INFORMAÇÕES IMPORTANTES)

**Problema:** fora da pergunta exata da FAQ, nada falava de como se assina. O sc01 proíbe imprimir, assinar à mão,
mandar foto e gerar outro contrato. Na 0523 sc01 T23, o sistema reenviou o link (`pediu_link`), e o prompt não dizia que
quem reenvia é o sistema.

ANTES: (só a linha dos honorários)

DEPOIS (3 linhas novas, depois da dos honorários):
```
- A assinatura é toda digital, pelo celular, no próprio link que o lead recebeu aqui no WhatsApp. Nunca peça para imprimir, assinar à mão, ir ao cartório ou mandar foto do contrato.
- O contrato já foi gerado e o link já está na conversa: nunca diga que vai gerar, refazer ou mandar outro contrato, e nunca escreva o link você mesma. Se o lead pedir o link de novo, o sistema reenvia o mesmo link sozinho: diga só que o link é o mesmo que foi enviado aqui na conversa.
```
**Por quê:** a regra passa a valer para qualquer variação ("mandar foto das folhas", "assinar no papel"). A frase sobre
o link não promete envio: ela continua certa mesmo quando o extrator não marca `pediu_link`.

## 3. Nunca dizer que conferiu a assinatura (INFORMAÇÕES IMPORTANTES)

**Problema:** 0426 sc10 T22: "Já confirmei aqui e o sistema também mostra que sua assinatura está completa". 0426 sc11
T24: "Vou verificar aqui para confirmar." Quem confere é a ação `verificar_assinatura`, que depois manda "Assinatura
confirmada" ou "Ainda não consta a sua assinatura".

ANTES: (não havia)

DEPOIS:
```
- Nunca diga que conferiu, confirmou ou viu a assinatura no sistema. Quem confere a assinatura é o sistema, e ele mesmo avisa o lead.
```
**Por quê:** é a mesma regra do FORMATO ("nunca diga que buscou ou conferiu algo se o sistema não disse"), dita no caso
concreto desta etapa.

## 4. Sem opinião jurídica (INFORMAÇÕES IMPORTANTES)

**Problema:** na lista de micro-alucinações da rodada aparecem "não ter recebido auxílio-doença pode complicar" e
"podemos incluir sim" (sc03 T23–T24, ainda no Contrato). A pergunta pode voltar na Assinatura.

ANTES: (não havia)

DEPOIS:
```
- Nunca dê opinião sobre o caso do lead (se tem chance, se algo "pode complicar", se uma lesão "conta"). Quem avalia o caso é o advogado responsável.
```

## 5. Não vender de novo (PERSONALIDADE E COMUNICAÇÃO)

**Problema:** 0426 sc01 T26 e T29: o lead fala da mão que falha, e a IA responde "Isso mostra como o auxílio-acidente pode
ajudar no seu dia a dia" e "Vamos tentar assinar o contrato juntos agora?". É venda e pressão numa etapa em que o lead
já aceitou.

ANTES: (não havia)

DEPOIS:
```
-Nesta etapa não venda de novo: se o lead falar da dor, do trabalho ou da sequela, acolha em uma frase curta, sem explicar o benefício de novo, e siga a condução da assinatura.
```

## 6. FAQ nova: prazo

**Problema:** 0426 sc02 T26: "pode levar alguns meses (...) acelerar o máximo possível". 0523 sc02 T25: "pode levar
alguns meses (...) agilizar o que for possível". 0426 sc03 T26: "esse processo pode levar alguns dias". O roteiro não
tinha resposta para prazo, e o modelo improvisou.

ANTES: (não havia)

DEPOIS:
```
-Quanto tempo demora o processo? / Vocês demoram para chamar de novo? → “Cada caso tem um tempo diferente, porque depende da análise do INSS.” e, em outro balão, “Nossa equipe vai te avisando por aqui a cada nova etapa.” Nunca diga prazo nenhum: nada de dias, dias úteis, semanas, meses, anos, “alguns dias”, “alguns meses” ou “em breve”.
```
**Por quê:** o modelo agora tem uma resposta pronta e verdadeira. A lista nomeia as formas vagas ("alguns meses") que o
modelo usou para fugir do número.

## 7. FAQ nova: "já assinei"

**Problema:** 0523 sc03 T26: "Agora vamos cuidar do processo para garantir o melhor resultado possível" foi barrado pela
trava, e a resposta refeita disse "Agora vamos começar o processo para conseguir o benefício". Mais uma repetição pausaria
o lead. 0523 sc02 T26: "Que bom que já assinou o contrato. Posso ajudar com mais alguma dúvida...?". 0426 sc10 T22: "Já
confirmei aqui...".

ANTES: (não havia)

DEPOIS:
```
-Já assinei / Pronto, assinei / Ele assinou → responda em 2 balões: “Que bom, [primeiro nome]! Obrigada pela confiança.” e “Assim que a assinatura for confirmada, a nossa equipe dá andamento ao seu caso e vai te avisando por aqui a cada nova etapa.” Depois disso não faça pergunta nenhuma, não diga prazo, não diga que já viu ou confirmou a assinatura e não fale de resultado (nada de “garantir”, “garantia”, “o melhor resultado”, “conseguir o benefício” ou “você tem direito”). Se na mesma mensagem o lead perguntar quanto tempo demora, junte a resposta da FAQ de tempo, sem prazo.
```
**Por quê:** a resposta agradece e explica o próximo passo, sem prazo e sem resultado. "Assim que a assinatura for
confirmada" fica certo nos dois desfechos do sistema: "Assinatura confirmada" ou "Ainda não consta". As expressões que a
trava barrou aparecem pelo nome, porque o gpt-4.1-mini segue melhor uma lista concreta do que "não prometa". A sc03
junta "assinou" e "vocês demoram?" na mesma fala, e a última frase da regra cobre esse caso.

## 8. Retomada da condução sem pergunta

**Problema:** 0523 sc02 T25 e T26, 0426 sc02 T25 e T26: depois de cada dúvida, a resposta termina com "Você tem alguma
dúvida sobre o contrato...?" ou "Posso ajudar com mais alguma dúvida?". O FORMATO manda retomar a pergunta pendente, mas
na Assinatura nenhuma estava definida. Na sc01, o "retomar" virou "conseguiu abrir o link?" a cada turno.

ANTES: (não havia)

DEPOIS (depois das FAQs, e uma regra nova nas REGRAS DE ATENDIMENTO):
```
Retomada da condução: quando você responder uma dúvida e o lead ainda não tiver dito que assinou, termine com uma frase curta, sem pergunta, como “Quando terminar de assinar pelo link, me avisa por aqui.” Se a sua resposta anterior já terminou com essa frase, não use de novo: termine só com a resposta à dúvida.
```
```
* Não termine as respostas com pergunta genérica (“posso ajudar com mais alguma coisa?”): use a retomada da condução.
```
**Por quê:** a etapa ganha uma retomada que não é pergunta, então não pede resposta e não vira laço. O limite de uso
evita a repetição palavra por palavra.

## 9. Código que não chega: 2 orientações e depois a equipe (DÚVIDA CÓDIGO DE ASSINATURA)

**Problema:** sc01 nas duas rodadas, T23–T32. O lead diz que o código não veio e pede para mandar pelo WhatsApp. A IA
alterna "já olhou o spam?" e "conseguiu abrir o link?" até o limite de 32 turnos. Na 0523 foram 4 `pergunta_repetida`
(alta), `nao_concluiu`, estado `ativo` (esperado `pausado`) e nenhum aviso à equipe. Outros erros vistos:
- 0426 T24: inventou motivo ("por questão de segurança");
- 0523 T28: presumiu que o lead achou o código ("Que bom que conseguiu encontrar o código na caixa de spam") quando ele só
  disse "Sim";
- 0523 T26–T27: pediu de novo o e-mail que o lead já tinha dado.

ANTES:
```
Em alguns casos, é solicitado um código que chega por e-mail ao cliente, mas ele geralmente tem dificuldade para encontrá-lo. Se o lead disser que a assinatura está pedindo um código ou token e ele não consegue encontrar ou usar, o sistema percebe sozinho a dificuldade na assinatura, pelas palavras do lead, e avisa a equipe: você não aciona nada. Responda de forma curta e acolhedora e continue ajudando normalmente. Nunca diga que vai gerar outro contrato.
```
DEPOIS (resumo; o texto inteiro está no `assinatura.md`):
```
Você tem no máximo 2 orientações para o código, nesta ordem. [...] nunca repita uma orientação já dada, nem com outras palavras.
1ª orientação → “O código chega no e-mail. Às vezes demora uns minutinhos.” + “Dá uma olhada também na caixa de spam ou lixo eletrônico. Se na tela tiver a opção de reenviar o código, toque nela.” Sem pergunta depois.
2ª orientação → (se pediu pelo WhatsApp) “Esse código é enviado pelo próprio sistema de assinatura. Eu não consigo mandar por aqui.” + “Confere se o código não chegou no e-mail que você informou no contrato ou por mensagem aqui no WhatsApp.” (cita o e-mail dos DADOS numa afirmação) + “Se não encontrar, me avisa que a nossa equipe te ajuda com a assinatura.” Sem pergunta depois.
Depois das 2 orientações, qualquer nova mensagem sobre o código ou a assinatura que não seja “achei”/“assinei” (inclui “não sei”, repetir o e-mail, pedir de novo pelo WhatsApp) → “Entendi, [primeiro nome]. Vou pedir para a nossa equipe te ajudar com a assinatura por aqui.” e "notificacao": "analise_humana".
- “depois eu olho” → “Combinado! Quando olhar, me avisa por aqui.” (sem pergunta; não conta como nova dificuldade)
- “sim”/“olhei”/repetir o e-mail não quer dizer que achou o código.
- Nunca dizer que manda o código pelo WhatsApp/SMS, nunca inventar motivo (“por segurança”), nunca gerar outro contrato, nunca inventar outro jeito de assinar.
```
**Por quê:**
- A escada tem fim: no máximo 2 orientações (spam/reenviar; conferir o e-mail e o WhatsApp), e depois a equipe.
- A saída não depende só do extrator: se ele marcar `dificuldade_assinatura`, o sistema pausa e responde sozinho; se não
  marcar (como nas duas rodadas), o agente preenche `analise_humana`, que o motor já trata como aviso com pausa
  (`turno.py`, "Agente pediu: analise_humana"). As duas saídas chegam ao `pausado` que o sc01 espera.
- As orientações não terminam em pergunta, então não há "conseguiu?" para repetir.
- O e-mail aparece citado numa afirmação, como manda o FORMATO, e não numa pergunta.

Simulação no papel do sc01 (falas do cartão):
- T23 "o código não veio" → 1ª orientação;
- T24 "manda no zap?" → 2ª orientação;
- T25 "depois do serviço eu olho" → "Combinado!...";
- T26 "não sei te dizer" → equipe + `analise_humana` → `pausado`.

As falas novas evitam as palavras que fazem o lead simulado responder outra coisa ("número", "dificuldade",
"celular" em pergunta). A orientação que fala de "e-mail" é inevitável. Se o lead responder com o e-mail, isso já cai em
"depois das 2 orientações".

## 10. Uma orientação por problema nos outros erros de assinatura; dado errado no contrato (DÚVIDA MUITO DIFÍCIL)

**Problema:** "que você não consegue resolver depois de orientar" não diz quantas vezes orientar. Também faltava saída
para o lead que vê um dado errado no contrato: o papel não tem `zapsign` (`acoes: []`), e o prompt proíbe pedir dados e
gerar outro contrato.

ANTES:
```
Se o lead tiver um problema **para assinar** (link não abre, erro, selfie, documento, código) que você não consegue resolver depois de orientar, preencha a notificação `analise_humana` (uma pessoa da equipe assume).
```
DEPOIS:
```
Se o lead tiver um problema **para assinar** (link não abre, erro, selfie, documento, código) que você não consegue resolver depois de orientar, preencha a notificação `analise_humana` (uma pessoa da equipe assume). Você tem no máximo UMA orientação por problema (as da FAQ, acima; para o código valem as 2 orientações da seção do código): se o lead voltar a falar do mesmo problema depois dela, responda “Entendi, [primeiro nome]. Vou pedir para a nossa equipe te ajudar com a assinatura por aqui.” e preencha `analise_humana`.
Se o lead disser que um dado do contrato está errado (nome, CPF, endereço), não peça os dados de novo e não diga que vai gerar outro contrato: diga que vai pedir para a nossa equipe corrigir o contrato e preencha `analise_humana`.
```
**Por quê:** "Não consigo abrir o link" e "Está demorando a carregar" passam a ser a orientação única. Na 2ª queixa, a
equipe assume. O dado errado vai para uma pessoa, que é quem pode refazer o contrato nesta etapa.

## 11. Lesão nova "conta também?" (DÚVIDA MUITO DIFÍCIL)

**Problema:** 0523 sc03 T23–T24 (no Contrato): "se ele tem relação com o acidente, podemos incluir sim na solicitação".
No achado da sc03 T13 (`analise_rodada2.json`), a IA pediu "comprovantes médicos ou laudos" sem o roteiro mandar. A pergunta pode voltar na Assinatura.

ANTES: (não havia)

DEPOIS:
```
Se o lead perguntar se outra lesão, doença ou sequela “conta também” ou entra no processo, nunca diga que entra, que “podemos incluir” ou que “vamos incluir”, e não peça documento, laudo nem exame. Responda: “Quem avalia isso é o advogado responsável, com base nos seus documentos médicos. Vou registrar essa informação para ele.” e retome a assinatura.
```
**Por quê:** segue a regra que já existia para dúvida de conteúdo (registrar para o advogado e retomar). O texto vem
pronto, e as expressões proibidas aparecem pelo nome.

## 12. Seção nova "NÃO FICAR EM LAÇO"

**Problema:** 0426 sc01 T25–T32 e 0523 sc01 T29–T32. "Conseguiu abrir o link?" e "conseguiu assinar?" apareceram 5 a 6
vezes, cada uma com outras palavras.

ANTES: (não havia)

DEPOIS:
```
## NÃO FICAR EM LAÇO
- Antes de cada pergunta, leia a conversa: se você já fez essa pergunta (ou uma parecida, como “conseguiu abrir o link?”, “conseguiu assinar?”, “já olhou o spam?”, “conseguiu achar o código?”), NÃO pergunte de novo.
- “Conseguiu abrir o link?” / “Conseguiu assinar?” → no máximo UMA vez em toda a conversa.
- Se o lead responder outra coisa (fala da dor, do trabalho, “não sei”), acolha em uma frase curta e termine sem pergunta. Se ele estava com problema para assinar e você já deu as orientações, siga a regra “Depois das 2 orientações”.
- Nunca chame o lead para “tentar juntos agora” nem insista para assinar na hora.
```
**Por quê:** "parecida" com exemplos fecha a brecha da paráfrase. "Não sei" depois das orientações passa a ter saída
(a equipe), em vez de mais uma pergunta.

## 13. Pergunta de depois dos áudios do endereço: uma vez só (Localização e Rede Social)

**Problema:** na rodada, o "Conseguiu entender certinho...?" foi repetido (lista de micro-alucinações). Aqui as perguntas
"Conseguiu entender direitinho?" e "Certo! Podemos prosseguir?" não tinham limite.

ANTES: (não havia; links e textos iguais)

DEPOIS (linha nova depois do 2º áudio):
```
Cada áudio do endereço vai no máximo uma vez na conversa, e cada pergunta de depois dele também. Se o lead já respondeu, não pergunte de novo: siga com a retomada da condução.
```
**Por quê:** os 2 links de mídia e os textos ficam iguais. Só entra o limite.

## 14. REGRAS DE ATENDIMENTO

**Problema:**
- "* Falar algo incoerente ou fora do padrão." e "* Dizer “vou esperar”..." perderam o "Nunca" e podem ser lidas como
  ordens.
- Faltavam as regras de não repetir pergunta, de não prometer, de não dar prazo e de não fechar com pergunta genérica
  (itens 6 a 9).

ANTES:
```
* Falar algo incoerente ou fora do padrão.
* Dizer “vou esperar” ou “vou ver depois”.
(...)
* Nunca repita a mesma mensagem ou áudio.
```
DEPOIS:
```
* Nunca fale algo incoerente ou fora do padrão.
* Nunca diga “vou esperar” ou “vou ver depois”.
(...)
* Nunca repita a mesma mensagem ou áudio.
* Nunca pergunte o que o lead já respondeu: antes de perguntar, confira a conversa.
* Nunca prometa resultado: não use “garantir” nem “garantia” ao falar de benefício, direito ou resultado, e nunca diga “você tem direito”.
* Nunca diga prazo do processo em dias, semanas, meses ou anos.
* Não termine as respostas com pergunta genérica (“posso ajudar com mais alguma coisa?”): use a retomada da condução.
```
**Por quê:** as duas linhas antigas só ganharam o "Nunca" que o sentido pede. O resto da lista do escritório ficou
igual, com o "Faça uma pergunta por vez." duplicado.

## 15. Passagem e frases de troca de outras etapas (REGRAS DE ACIONAMENTO DE TOOLS)

**Problema:** a seção veio copiada do SDR. Ela mandava passar o lead para `closer`, `desqualificado` e `periododegraca` e
"Após passar o lead para `periododegraca`, envie o seguinte texto: > Agora vou confirmar algumas informações importantes
sobre seu vínculo com o INSS, tudo bem?". Neste papel `destinos` é `[]`: o esquema só aceita `transferir_para` vazio.
Pela regra, o modelo só podia escrever a frase de troca **sem transferir**, que é o defeito que o usuário pediu para
corrigir.

ANTES:
```
A IA deve acionar **apenas UMA Tool por vez**.
## Tool `closer` (requisitos)  ## Tool `desqualificado` (requisitos)  ## Tool `periododegraca` (5 condições)
Após passar o lead para `periododegraca`, envie o seguinte texto:
> Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?
```
DEPOIS:
```
Nesta etapa não há passagem para outra etapa nem ferramenta para acionar: deixe "transferir_para" e "ferramenta" sempre vazios. O lead já foi qualificado e o contrato já foi gerado: **não qualifique nem desqualifique o lead de novo**, não refaça perguntas de qualificação e nunca escreva frases de passagem de outras etapas (como a de confirmar o vínculo com o INSS, a de que podemos ajudar no caso ou a que pede o nome completo).
## Tool `closer` / ## Tool `desqualificado` / ## Tool `periododegraca`
* Não está ligada nesta etapa. Nunca acione.
```
**Por quê:**
- Os títulos da seção ficaram.
- A frase de troca do `periododegraca` saiu deste papel. Ela continua idêntica no snapshot (`papeis.periododegraca.mensagem_troca`)
  e no papel que a diz. Não ficou citada nem como proibida, porque o gpt-4.1-mini tende a copiar o texto que vê entre aspas.
- As frases de passagem são descritas pelo assunto, sem citação.

## 16. SISTEMA DE NOTIFICAÇÃO: quando o agente preenche `analise_humana`

ANTES: (só o parágrafo "Os avisos à equipe (...) são percebidos pelo sistema sozinho")

DEPOIS (o parágrafo fica e entra mais um):
```
A única notificação que você preenche nesta etapa é "analise_humana", e só nos casos das seções “DÚVIDA CÓDIGO DE ASSINATURA” e “DÚVIDA MUITO DIFÍCIL”: problema para assinar que continua depois das orientações, ou dado do contrato errado. No resto do tempo deixe "notificacao" vazio.
```
**Por quê:** junta num lugar só os gatilhos do agente. O resto continua com o extrator.

## 17. Erros de digitação na objeção "Segurança no trabalho"

ANTES: `Ou seja, seu emprego não será afetado.e não prejudica a empresa em nada, caso não queria a empresa não precisa ficar sabendo`
DEPOIS: `Ou seja, seu emprego não será afetado. E não prejudica a empresa em nada: caso não queira, a empresa não precisa ficar sabendo.`

**Por quê:** o modelo copia esse texto para o lead. O conteúdo não mudou.

---

## Conferência (script `conferir_assinatura.py`, no scratchpad da sessão)

- **Frases de troca:** a config do papel tem `mensagem_troca: null`, `boas_vindas: null` e `destinos: []`, então este
  papel não deve dizer nenhuma frase de troca. Nenhuma das 4 frases do snapshot aparece pela metade ou alterada no
  texto novo. A do `periododegraca` saiu daqui (item 15) e continua idêntica no snapshot.
- **Links:** os 7 links do fiel continuam iguais: 5 de redes e site, e os 2 áudios de endereço. Não entrou nenhum link
  novo.
- **"garant":** aparece em 2 linhas, e as duas são proibições ("nada de", "não use").
- **Falas de roteiro:** as 37 falas entre aspas, tirando as listas de proibidos, passaram pela trava de promessa do motor
  (`travas.trecho_de_promessa`) e pelos `proibido` do sc01, sc02, sc03, sc10 e sc11 sem nenhum acerto. Nenhuma pergunta
  tem mais de 100 caracteres.
- **sc02:** a FAQ de imprimir casa com o `obrigatorio_em.assinatura`.
- **Saídas:** a FAQ antiga e a ordem "envie o seguinte texto" saíram. Todas as seções (#) do fiel continuam.

Nada disso foi medido com o modelo: não houve rodada real. Para medir, troque a instrução no snapshot e rode
sc01/sc02/sc03/sc10/sc11.


## Corretor, rodada 1 (2026-11-25)

Mudanças mínimas pedidas pela revisão. Frases de troca (mensagem_troca), links de mídia e dados do escritório intactos.

- **[12] A 2ª orientação do código inventava o canal WhatsApp.** Confirmado: dizia "não consigo mandar por aqui" e logo depois mandava procurar o código "por mensagem aqui no WhatsApp".
  - ANTES: "Confere se o código não chegou no e-mail que você informou no contrato ou por mensagem aqui no WhatsApp."
  - DEPOIS: "Confere se o código não chegou no e-mail que você informou no contrato."
  - Nota nova: o código só chega no e-mail; a IA nunca manda procurar no WhatsApp ou por SMS e não repete o spam da 1ª orientação.
- **[13] "Já assinei" repetia a mensagem do sistema.** Confirmado: "obrigada pela confiança" e "a equipe dá andamento... vai te avisando a cada nova etapa" saíam 2 a 3 vezes, contando com o pos_assinatura do sistema (app/contrato/dados.py).
  - "Já assinei".
    - ANTES: 2 balões ("Que bom, [primeiro nome]! Obrigada pela confiança." + "...a nossa equipe dá andamento ao seu caso e vai te avisando por aqui a cada nova etapa.").
    - DEPOIS: 1 balão, "Que bom, [primeiro nome]! Assim que a assinatura for confirmada, você recebe a confirmação aqui mesmo."
  - Junto com a pergunta de tempo, vai só o 1º balão da FAQ de tempo.
  - FAQ de tempo: se a IA já disse nesta conversa que a equipe vai avisando a cada etapa, não diz de novo.
