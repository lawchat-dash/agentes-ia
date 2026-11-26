# Mudanças na instrução do papel `sdr` (Sousa e Costa, para o NOSSO motor)

Arquivo: `avaliacao/agentes/sousa_costa_corrigido/sdr.md`. É a instrução completa do papel e entra em
`agente.etapas[codigo="sdr"].instrucao` do snapshot, no mesmo formato da atual (Markdown, mesmas seções).

Ponto de partida: a instrução fiel (`sousa_costa.json`), as trocas do SDR em `sousa_costa_sugerido.json` (1ª leva) e as
ideias do rascunho `n8n/01_SDR.txt` (os nomes de tool do n8n, como `qualificado` e "Definir departamento", não valem aqui).

Continua igual ao fiel:
- A config do papel: `papeis.sdr` tem `mensagem_troca: null` e `boas_vindas: null`, e os destinos são `periododegraca`,
  `closer` e `desqualificado`.
- As frases de troca dos destinos, letra por letra:
  - closer: "Maravilha! Nós podemos te ajudar no seu caso."
  - periododegraca: "Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?"
  - desqualificado: "Analisei com atenção o que você nos contou e, neste momento, pelas regras atuais, você não se enquadra nos critérios para esse benefício específico."
- A mensagem exata de "APÓS DESQUALIFICAR", a abertura, a pergunta do advogado, os 10 links, os dados do escritório,
  as 11 objeções e os 47 títulos de seção. Só um título mudou: a pergunta 2, de "ano" para "mês e ano".

## Por que o gpt-4.1-mini a 0.5 ainda errou com a 1ª leva (rodada 0523)

1. **A frase de troca do closer estava longe da regra que manda qualificar.**
   - A pergunta 4 dizia só "SIM → acionar Tool `closer`". A frase "Maravilha!..." ficava a 130 linhas, em "APÓS QUALIFICAR".
   - O FORMATO do motor diz "escreva a mensagem de passagem", e o modelo escreveu uma mensagem dele: "Ótimo saber que
     estava fichado...", "Obrigado por informar que está registrado desde 2021. Isso confirma que...".
   - Isso aconteceu em 4 de 10 conversas (sc01 T6, sc02 T5, sc03 T5, sc14 T5).
   - Nas outras, a frase veio depois de um eco (sc11 T5, sc18 T7, sc19 T5, sc20 T5).
   - Hoje o motor põe a frase sozinho quando ela falta (`_com_frase_de_troca`). Mesmo assim, o 2º balão "Posso te
     explicar como funciona o Auxílio-Acidente?" se perdia, e o lead ficava sem pergunta para responder.
2. **"Caso o Lead já tenha informado alguma resposta, não pergunte novamente" é abstrato demais para o modelo mini.**
   - Ele não ligava "na época eu era registrado" (sc02 T2) à pergunta 4.
   - Ele não ligava "era registrado de vigia" (sc18 T5) ao fim das perguntas e seguiu a lista numerada: MEI (T5) e
     prova rural (T6).
   - Faltava uma lista de respostas que já contam e a regra "5 a 8 só para quem disse NÃO na 4".
3. **O eco gerava invenção.**
   - Repetir a resposta trouxe número calculado: "foi em 2014 então", a partir de "uns 12 anos" (sc01 T4).
   - Trouxe também número lido como prazo: "cerca de 8 meses" (sc03 T4).
   - E trouxe opinião: "Isso confirma que você estava com carteira assinada" (sc14 T5).
4. **A dúvida do lead ficava sem resposta.** Exemplos: "vale mesmo assim?" (sc14 T2) e "isso q é o tal auxilio doença?"
   (sc02 T2). O prompt não dava uma resposta curta permitida, e o modelo só seguia a lista.
5. **Aposentado não desqualificava na hora.** A regra estava só nas TRAVAS, longe das perguntas. Em sc13 T4 o modelo fez
   a próxima pergunta, e com dois "?". Em T5 explicou o motivo ("não tem direito") antes da mensagem exata.
6. **5.1 e TRAVAS se contradiziam.**
   - A 5.1 mandava desqualificar com mais de 3 anos de saída. As TRAVAS e os "Casos especiais" mandavam ao período de
     graça quem teve CLT antes.
   - A pergunta da 5.1 era usada com quem não era MEI (sc14 0317 T7, sc16 0426 T5).
   - A frase do período de graça saiu junto com a transferência para `desqualificado` (sc15 0523 T7, barrada; sc15
     0317 T6).

## Lista de mudanças

### 1. Abertura: link em balão próprio e abertura que não repete o relato
- **Problema:** o motor responde em balões (`mensagens`), não com `\n\n`. Nos testes o link saiu certo. Mas se o lead já
  conta o acidente na 1ª mensagem, o texto fixo pede de novo "Me conta como aconteceu", e isso é pergunta repetida.
- **ANTES:** `...Envie o link SOZINHO primeiro, depois o texto. Use \n\n para separar...`
- **DEPOIS:**
  - `...Envie o link SOZINHO no primeiro balão e o texto no balão seguinte...`
  - Mais duas regras:
    - Se a 1ª mensagem já contar o acidente, mande link + "Olá! Me chamo Ana..." + acolhimento + a próxima pergunta.
    - O vídeo vai só uma vez.
- **Por quê:** o formato fica no do motor (`separar_midias`), e o lead não responde duas vezes a mesma coisa.

### 2. Novo bloco "COMO ACIONAR AS TOOLS NESTE ATENDIMENTO"
- **Problema:** passagens sem frase ou com texto antes dela (sc01 T6, sc02 T5, sc03 T5, sc14 T5, sc11/sc18/sc19/sc20 T5-T7).
  Houve também frase de outro destino: `periododegraca` com `transferir_para: desqualificado` (sc15 0523 T7, sc15 0317 T6).
- **ANTES:** não existia. Cada pergunta dizia só "acionar Tool `x`".
- **DEPOIS:**
  - Uma tabela destino → `transferir_para` → balões exatos.
  - Seis regras curtas:
    - Decidiu, acione nesta resposta.
    - Nada antes da frase.
    - Não troque a frase.
    - Nunca uma frase sem a tool dela, nem a tool sem a frase.
    - Não explique a decisão.
    - `transferir_para` fica vazio enquanto falta pergunta.
- **Por quê:**
  - "Acionar Tool" vira os campos do JSON do motor.
  - A frase fica antes das perguntas, onde o modelo a lê na hora de decidir.
  - Nunca há frase sem transferir. Isso evita a contradição com a inserção automática da frase pelo motor e com o
    `frase_de_outro_destino`.

### 3. "ANTES DE CADA PERGUNTA", ordem das perguntas e "Respostas que JÁ CONTAM"
- **Problema:**
  - sc02 0523 T4 repetiu a CLT ("como eu falei, trabalhava registrado sim").
  - sc18 0523 T5/T6 perguntou MEI e prova rural a quem disse "era registrado de vigia".
  - sc15 0523 T5 perguntou MEI a quem abriu com "eu sou mei" e disse "trabalhava por conta".
  - sc15 0426 T7 confirmou "nunca trabalhou de carteira, certo?".
- **ANTES:** `**Caso o Lead já tenha informado alguma resposta, não pergunte novamente.**`
- **DEPOIS:**
  - A linha do escritório continua.
  - Vem depois "releia TODAS as mensagens do lead" e "'como eu falei' = você repetiu".
  - A ordem fica explícita: 1 → 2 → 3 → 4, e as perguntas 5 a 8 são só para quem disse NÃO na 4.
  - Uma lista mostra, por pergunta, as falas que já respondem: "era registrado", "registrado de vigia", "sou
    registrado desde [ano anterior]", "trabalhava por conta", "tava parado/tinha saído da transportadora", "na roça",
    "me aposentaram"...
- **Por quê:** o modelo mini segue a lista numerada ao pé da letra. Com exemplos concretos do que já conta, ele pula a
  pergunta em vez de repeti-la.

### 4. "Como responder entre as perguntas" (eco, conta, dúvida, laudo, lesão nova, prazo)
- **Problemas vistos:**
  - Eco com conta: "foi em 2014 então" (sc01 0523 T4) e "cerca de 8 meses" (sc03 0523 T4).
  - Eco como pergunta + pergunta nova: "maio de 2018, certo? / Você recebeu...?" (sc13 0426 T3, sc17 0426 T3/T5).
  - Dúvida sem resposta: "vale mesmo assim?" (sc14 0523 T2) e "isso q é o tal auxilio doença?" (sc02 0523 T2).
- **ANTES:** não existia.
- **DEPOIS:**
  - Acolher em poucas palavras, sem repetir datas, tempos, números e empresa, e sem conta.
  - No máximo um "?" e nada de "..., certo?".
  - Dúvida do lead: responder em 1 frase e retomar a pergunta pendente. Há três respostas prontas:
    - "O auxílio-acidente não depende de o acidente ter sido no trabalho."
    - "Isso mesmo, ficar encostado pelo INSS é o auxílio-doença."
    - "Quem avalia o seu caso é o nosso advogado..."
  - Não pedir laudo nem documento médico.
  - Com mais de um acidente, perguntar sobre o que deixou a sequela, sem prometer incluir lesão nova.
  - Nunca dar prazo.
- **Por quê:**
  - São as micro-alucinações da lista.
  - As respostas prontas não têm "direito", "garant" nem "vai receber", então passam na trava do catálogo (conferido
    no script).
  - O lead não fica sem resposta, e a condução não para.

### 5. Pergunta 2: mês e ano, obrigatória e com saída para "não sei"
- **Problema:**
  - Na 0317/0426 a pergunta do ano foi pulada em quase todas as conversas: 1 de 22 perguntou (achados g4, g5, g6, g7).
  - O corpo da pergunta 2 era cópia do corpo da 1.
  - "até hj" chegou a virar data do acidente (achado g6).
- **ANTES:**
  ```
  ### 2. Em qual ano aconteceu o acidente?
  Quando o lead contar sobre o acidente, acolha com empatia brevemente e depois continue.
  ```
- **DEPOIS:**
  - O título passa a ser "Em que mês e ano aconteceu o acidente?", e a pergunta é **OBRIGATÓRIA** antes da 3 e da 4.
  - Só se pula se a data estiver escrita pelo lead na conversa ("até hoje" não é data).
  - Sem mês, aceite o ano. Sem ano, pergunte "Mais ou menos em que ano foi?" uma única vez e aceite o que vier.
  - Não repetir a data nem calcular.
  - Não saber a data não desqualifica.
  - Nunca closer nem periododegraca sem esta pergunta.
- **Por quê:**
  - Na 0523 (já com a 1ª leva) a pergunta foi feita em 10 de 10 conversas. O que faltava era a saída: no sc01 o lead
    disse "uns 12 anos" e o modelo inventou "2014".
  - "Só vale data escrita pelo lead" protege contra o fato errado do extrator nos DADOS JÁ INFORMADOS.

### 6. Pergunta 3: o NÃO sem opinião
- **Problema:** "Ele não ter recebido auxílio-doença pode complicar, mas vamos ver o que dá pra fazer." (sc17-com 0317 T3).
- **ANTES:** só `* Se **SIM** → perguntar por quanto tempo`
- **DEPOIS:**
  - O SIM continua e pergunta o tempo só se o lead ainda não disse. Se ele não lembrar, aceite.
  - Entra o NÃO: "não comente nem avalie (não ter recebido auxílio-doença NÃO impede o pedido; nunca diga que 'pode
    complicar'). Siga direto para a pergunta 4."
- **Por quê:** a lacuna do NÃO foi preenchida pelo modelo com opinião jurídica inventada.

### 7. Pergunta 4: SIM qualifica no mesmo turno, "registrado desde X" é CLT na data
- **Problema:**
  - sc14 0317 (T4 e T6) perguntou a CLT 2x a quem disse "sou registrado no mercado desde 2021" e mandou para o período de graça
    pela 5.1.
  - sc18 0523 seguiu para a 5 depois de "era registrado de vigia".
  - Passagens sem frase (ver item 2).
- **ANTES:**
  ```
  * Se **SIM** → acionar Tool `closer`
  ...
  Exemplos importantes (...): 2 - Resposta do Lead "Sou fixado" ou "Sou fichado" -> Tool `periododegraca`
  ```
- **DEPOIS:**
  - SIM, com a pergunta 2 feita, aciona o closer NESTA resposta, com o JSON literal dos dois balões. As perguntas 5,
    5.1, 6, 7.1 e 8 NÃO são feitas.
  - "Registrado/fichado desde [ano anterior]", "era fichado na construtora", "registrado de vigia" e "no mesmo
    emprego até hoje" contam como SIM, mesmo sem o ano exato.
  - Registrado desde o MESMO ano: uma pergunta só, "Você já trabalhava nesse emprego quando o acidente aconteceu?".
  - Os exemplos "Sou fichado/Já fui CLT → periododegraca" valem SÓ quando o lead não confirma CLT na data.
  - A pergunta "Entendi está desempregado agora..." é só para quem falou no presente.
- **Por quê:**
  - O exemplo "Sou fichado → periododegraca" brigava com "SIM → closer".
  - O texto do escritório para "não trabalho" foi usado com quem disse "na época eu tava parado" (sc16 0426 T5).
  - Com o exemplo literal, a resposta da passagem fica sem espaço para eco.

### 8. Pergunta 5: só para quem disse NÃO na 4
- **Problema:** sc18 0523 T5 ("era registrado de vigia" → "você era MEI...?"). sc15 0523 T5 (MEI já dito).
- **ANTES:** sem condição.
- **DEPOIS:** `(Só pergunte se a resposta da pergunta 4 foi **NÃO** e o lead ainda não disse como trabalhava. Nunca pergunte a quem disse que era registrado/CLT na data.)`
- **Por quê:** é a pergunta de vínculo que mais se repetiu.

### 9. Pergunta 5.1: uma pergunta, sem promessa, e o conflito com as TRAVAS (DECISÃO REGISTRADA)
- **Problemas:**
  - O texto tinha dois "?" e prometia ("terá direito a receber uma indenização do INSS").
  - Foi usado com quem não era MEI (sc14 0317 T7, sc16 0426 T5).
  - Foi enviado junto com a transferência (sc16 0317 T4).
  - A regra ">3 anos → desqualificado" contradizia "Teve CLT antes → período de graça" (TRAVAS, "Sobre MEI", "Casos
    especiais"). Em sc15[saiu_ha_mais_de_3_anos] 0317 T6, o modelo misturou as duas: frase do período de graça com
    `transferir_para: desqualificado`.
- **ANTES:**
  ```
  > Quando você sofreu o acidente, há quanto tempo havia saído da última empresa? Eram meses ou já eram anos? Dependendo do tempo, pode ser que você ainda estivesse no período de graça e, com isso, terá direito a receber uma indenização do INSS.
  * Se o cliente foi demitido **a mais de 3 anos antes do acidente** → Acionar Tool `desqualificado`
  * Se o cliente informar que **nunca** trabalhou CLT → Acionar Tool `desqualificado`
  ```
- **DEPOIS:**
  ```
  > Quando sofreu o acidente, fazia meses ou anos que tinha saído da última empresa de carteira assinada? Dependendo do tempo, pode ser que você ainda estivesse no período de graça do INSS.
  Envie a mensagem acima SOZINHA e espere a resposta do lead. Não acione nenhuma Tool na mesma resposta em que envia esta pergunta.
  * Se o cliente informar que saiu **há anos** (inclusive mais de 3 anos antes do acidente) → Acionar Tool `periododegraca`. Não desqualifique pelo tempo aqui: quem teve CLT antes vai para o Período de Graça, que pergunta a data da saída e o seguro-desemprego, usa a conta do sistema e decide.
  * Se o cliente informar que **nunca** trabalhou CLT → Acionar Tool `desqualificado` na mesma resposta, sem pedir confirmação (...)
  ```
  - A 5.1 só é enviada a quem disse SIM na 5 e ainda não contou se já teve carteira.
  - Quem já disse "saí da loja uns 8 meses antes" vai direto ao `periododegraca`.
  - Quem já disse "nunca tive carteira" vai direto ao `desqualificado`.
- **Decisão:** quem teve CLT antes do acidente vai **sempre** para o `periododegraca`, mesmo que tenha saído há mais
  de 3 anos.
  - O Período de Graça (`periododegraca.md`) pergunta mês/ano da saída e seguro-desemprego, recebe a conta pronta nos
    FATOS DO SISTEMA e decide entre `closer`, `desqualificado` ou análise da equipe.
  - Mais de 3 anos está fora até do maior prazo (36 meses), então o lead é desqualificado lá, pelo cálculo e com o
    motivo certo.
  - Não se desqualifica por uma estimativa vaga ("uns anos").
  - A pergunta do escritório (meses ou anos) continua, porque a resposta dela já serve ao Período de Graça: o
    `periododegraca.md` corrigido lê "uns 8 meses", "nunca trabalhei de carteira" e "não sei" como resposta e não
    pergunta de novo.
- **Por quê:** tira a contradição sem mexer nas TRAVAS. O cenário sc15[saiu_ha_mais_de_3_anos] já aceita
  SDR → periododegraca → desqualificado. O sc15[teve_clt_ha_meses] continua exigindo a pergunta "meses ou anos" antes
  do período de graça, e ela continua aqui.

### 10. Perguntas 6 e 8: closer com a frase e prova rural só para quem é rural
- **Problema:**
  - Em sc17-com (0317 T5) a frase do closer foi trocada: "Ótimo! Com esses documentos, podemos ajudar no caso do seu
    pai. / Vou encaminhar para o próximo passo do atendimento."
  - Em sc18 0523 T6 a mensagem de prova rural foi enviada a um vigia CLT.
- **ANTES:** `* Se o cliente responder que **tem** um dos documentos descritos acima → acionar Tool `closer``
- **DEPOIS:**
  - `...→ acionar Tool `closer` NESTA resposta, com a mesma resposta exata da pergunta 4 (...)`
  - Na 8: `(É a mesma mensagem da pergunta 6: só para quem respondeu SIM na pergunta 6, e nunca duas vezes. Nunca envie a quem disse que era registrado/CLT, MEI ou autônomo.)`
- **Por quê:** a 6 e a 8 são a mesma mensagem, e o modelo as tratava como dois passos da lista.

### 11. Pergunta 7.1: saída para "nunca teve CLT"
- **Problema:** SIM e NÃO levavam os dois ao `periododegraca`, e faltava o caso de quem nunca teve carteira e não é
  rural. Isso gerava uma volta inútil pelo Período de Graça.
- **DEPOIS:** `* Se o lead já disse que **nunca** teve carteira assinada na vida, ou que nunca trabalhou (e não é segurado especial com prova) → acionar Tool `desqualificado``. Também é a trava das REGRAS PARA DESQUALIFICAR.
- **Por quê:** fica coerente com as TRAVAS e evita a trajetória sdr > periododegraca > desqualificado em sc15[nunca_clt].

### 12. REGRAS PARA QUALIFICAR: o ano não é dispensável
- **ANTES:** `* Sofreu acidente (em qualquer ano)`
- **DEPOIS:** `* Sofreu acidente (o ano não desqualifica, mas precisa ser perguntado: pergunta 2)`
- **Por quê:** o "(em qualquer ano)" era lido como "não precisa perguntar o ano" (achados g4 e g7).

### 13. Confirmação antes de desqualificar: sem tool e só quando falta clareza
- **Problema:**
  - sc13 0426 T4 confirmou "foi aposentado por invalidez em 2021, certo?" a quem tinha acabado de dizer "me aposentaram".
  - sc13 0523 T4 fez outra pergunta, com dois "?".
- **ANTES:** `> Para todas perguntas acima, caso for necessário pergunte para confirmar ao cliente.`
- **DEPOIS:** a linha do escritório continua, com o acréscimo: `A confirmação é uma resposta SEM Tool ("transferir_para" vazio), com uma pergunta só (...). Se o lead já disse com clareza (ex.: "me aposentaram", "nunca trabalhei de carteira", "recebo o auxílio-acidente"), não confirme: acione na mesma resposta.`
- **Por quê:** sem isso, o modelo perguntava "certo?" e transferia no mesmo turno, ou repetia o que o lead já tinha dito.

### 14. REGRAS PARA NÃO DESQUALIFICAR: o que não é problema e o que não se diz ao lead
- **Problema:** a regra de decisão foi copiada ao lead.
  - "Sobre o local, não tem problema, pode ter direito sim." (sc14 0317 T2)
  - "Sobre o acidente fora do trabalho, pode ter direito sim, se estava segurado pelo INSS na época." (sc14 0426 T3)
- **DEPOIS:** duas linhas novas:
  - "Não ter recebido auxílio-doença, não ter guardado documentos médicos ou não lembrar a data exata NÃO desqualifica e
    não deve ser comentado como problema."
  - "(Estas regras são para a sua decisão. Ao lead, não diga que ele 'pode ter direito' nem que 'tem direito' (...))"
- **Por quê:**
  - "ele PODE ter direito normalmente" é regra de decisão do escritório.
  - Copiada ao lead, vira afirmação de direito, que a trava "você tem direito" barra e que, repetida, pausa o lead.

### 15. APÓS QUALIFICAR: frase exata, primeira, no mesmo turno, com exemplos certos e errados
- **Problema:** item 2. Além disso, "Conseguiu entender certinho como funciona o benefício?" já foi repetido (laço).
  Essa pergunta é do closer.
- **ANTES:** `Quando o lead atender aos requisitos, enviar: > Maravilha!... Depois: > Posso te explicar...? * Se responder **SIM** → manter a chame a tool `closer`` + o link do áudio e "Conseguiu entender...".
- **DEPOIS:**
  - Tudo na mesma resposta, com os dois balões exatos, nada antes e nenhuma outra pergunta.
  - Um exemplo CERTO em JSON.
  - Quatro exemplos ERRADOS reais (sc01, sc14, sc18, sc17).
  - O áudio e o "Conseguiu entender" ficam marcados como da etapa seguinte. Link e texto continuam no lugar.
- **Por quê:** o modelo mini copia exemplos. O erro real escrito como "errado" é o que mais pesa contra repeti-lo.

### 16. APÓS DESQUALIFICAR: mensagem exata, nada antes
- **Problema:** "Você mencionou que é aposentada. Infelizmente, quem já é aposentado não tem direito ao
  auxílio-acidente. Analisei..." (sc13 0523 T5). E a frase do período de graça com `desqualificado` (sc15 0523 T7).
- **DEPOIS:**
  - A mensagem vai na MESMA resposta, sem nada antes.
  - Sem motivo, sem "não tem direito" e sem a frase do período de graça.
  - A exceção do advogado aponta para a regra ADVOGADO.
  - Há dois exemplos errados reais. A mensagem exata continua idêntica.
- **Por quê:** a explicação do motivo é do Desqualificado (resumo + confirmação). O SDR só passa.

### 17. TRAVAS: aposentado na hora e "Sobre MEI" coerente com a decisão do item 9
- **ANTES:**
  - `* **Aposentado → DESQUALIFICADO EM QUALQUER PERGUNTA**`
  - `...Se teve CLT antes → caminho Período de Graça.`
- **DEPOIS:**
  - Aposentado: `(...) acione `desqualificado` na mesma resposta; não faça a próxima pergunta do roteiro)`.
  - "Sobre MEI": `Se teve CLT antes → caminho Período de Graça (mesmo que tenha saído há anos: a conta do tempo é feita lá, nunca aqui).`
- **Por quê:**
  - sc13 0523 T4 seguiu perguntando a CLT depois de "me aposentaram por invalidez".
  - A trava do MEI agora diz a mesma coisa que a 5.1.

### 18. ADVOGADO: pergunta sozinha, passagem coerente com o motor e retomada da pergunta 2
- **Problema:**
  - Na passagem para `desqualificado`, o motor põe a frase "Analisei com atenção..." como 1º balão quando ela falta
    (`_com_frase_de_troca`, `inserir_frase_de_troca` padrão).
  - Com só a mensagem de ética, o lead recebia as duas numa ordem que o prompt não previa.
  - Em sc12[so_no_passado] 0317 T5, o fluxo "normal" retomado pulou a pergunta do ano.
- **DEPOIS:**
  - A pergunta de confirmação vem antes da próxima pergunta do roteiro, sozinha.
  - Advogado atuando hoje: 1º balão é a frase do desqualificado, 2º a mensagem da ética, sem o resto de "APÓS
    DESQUALIFICAR".
  - "NÃO tem mais / nunca teve": retoma a próxima pergunta que falta, inclusive a pergunta 2.
  - A mensagem da ética e a pergunta continuam literais.
- **Por quê:** a resposta fica igual ao que o motor manda de qualquer jeito, e o lead não recebe uma ordem estranha.
  - Se o escritório preferir só a mensagem da ética, o caminho é `inserir_frase_de_troca: false` em
    `papeis.desqualificado`.
  - Mas isso também tira a frase das outras desqualificações que vêm sem ela.
  - Ficou como está (ver pendências).

### 19. CONDUTA DA IA: uma pergunta, sem eco, sem opinião, sem promessa, sem prazo, sem "conferi"
- **ANTES:** `* Faça somente uma pergunta por vez`
- **DEPOIS:**
  - A linha diz "no máximo UM '?' por resposta (a exceção são os textos exatos do roteiro)" e traz o exemplo errado
    de sc13 0523 T4.
  - Seis linhas novas:
    - Conferir antes de perguntar.
    - Não ecoar nem calcular.
    - Não dar opinião jurídica ("pode complicar", "isso confirma que...").
    - Nunca "você tem direito/terá direito" nem "garantir" ligado a resultado.
    - Nunca dar prazo.
    - Só afirmar o que o lead ou uma linha "(sistema)" disse, sem nunca dizer que conferiu ou consultou.
- **Por quê:** as regras gerais ficam juntas, como lembrete. As do item 4 ficam junto das perguntas, onde o modelo decide.

### 20. REGRA CRÍTICA SOBRE FERRAMENTAS: o que é "executar" neste motor
- **ANTES:** `* Apenas **EXECUTE** a ferramenta diretamente através do sistema de tools`
- **DEPOIS:** `...: preencha "transferir_para" e escreva a frase de passagem do destino (ver "COMO ACIONAR AS TOOLS NESTE ATENDIMENTO")`
- **Por quê:** no nosso motor não há chamada de tool para os destinos, só o campo do JSON.

### 21. Endereço: cada áudio uma vez e volta à pergunta pendente
- **DEPOIS:** `(Cada áudio do endereço vai uma vez só. Depois que o lead responder, volte para a pergunta do roteiro que ficou pendente.)`
- **Por quê:** "Nunca repetir vídeos ou áudios" + o FORMATO do motor ("responda a dúvida e retome a pergunta").
  Responder dúvida sem retomar a condução está na lista de erros.

### 22. OBJEÇÕES: reconduzir = pergunta pendente, uma pergunta só
- **Problema:** cada objeção termina numa pergunta de fechamento ("Quer seguir?", "Podemos avançar?"). No SDR não há
  fechamento: a resposta ficava com duas perguntas, ou com a da objeção no lugar da pergunta do roteiro.
- **DEPOIS:** os textos das 11 objeções continuam idênticos. Em "QUANDO USAR" entra: `Nesta etapa, "reconduzir" é voltar para a pergunta do roteiro que ficou pendente: use o texto da objeção sem a pergunta final dele e termine com a pergunta pendente (uma pergunta só na resposta).`
- **Por quê:** as objeções continuam idênticas, e a condução volta ao roteiro.

### 23. REGRAS DE ACIONAMENTO DE TOOLS: frase no mesmo turno e nada de pergunta de demissão aqui
- **DEPOIS:**
  - Tool `closer`:
    - Exige a pergunta 2 feita.
    - Pede os dois balões exatos na mesma resposta.
  - Tool `desqualificado`:
    - Pede a mensagem exata, nada antes.
  - Tool `periododegraca`:
    - O 2º critério passa a incluir "não sabe se ainda estava registrado" e "sem emprego na época".
    - O "PROIBIDO após NÃO" vale só para o "NÃO sozinho".
    - A frase é a única mensagem.
    - Só depois que o lead respondeu a última pergunta.
    - A frase nunca serve para qualificar ou desqualificar.
    - Data da saída e seguro-desemprego são perguntados na próxima etapa.
- **Por quê:**
  - Em sc16 0426 sem_seguro T6, o modelo juntou eco + "certo?" + a frase (dois "?").
  - Em sc16 0317 T4, ele enviou a 5.1 e transferiu no mesmo turno. A resposta "nunca trabalhei de carteira" caiu no
    Período de Graça. O motor hoje adia uma vez essa troca (`_segurar_transferencia`), mas o certo é o prompt não
    fazer isso.
  - Perguntar a data da demissão no SDR duplicaria a pergunta 3 do Período de Graça.

### 24. Casos especiais do período de graça: limite para quem é CLT na data
- **Problema:** sc01 (lead "uns 12 anos", "era fichado na construtora"). "Incerteza de data em acidente antigo →
  periododegraca OBRIGATORIAMENTE" mandaria um CLT na data ao Período de Graça. O destino certo é `closer`.
- **ANTES (1ª leva):** `Estes casos valem quando o lead não sabe a data do vínculo ou diz que saiu do emprego. (...)`
- **DEPOIS:** `Estes casos valem quando o lead NÃO confirma que estava registrado na data do acidente (...). Quem diz com clareza que estava registrado na data (...) é CLT na data → Tool `closer`, mesmo que não lembre o ano exato do acidente.`
- **Por quê:** a incerteza que importa é a do vínculo. Não saber o ano exato do acidente não muda o destino de quem
  era registrado.

## Conferência por script

Script: `C:\Users\joaov\AppData\Local\Temp\claude\3daca395681118a1\65175654-ced8-4918-a48b-f45988c6d47b\scratchpad\sdr\conferir_sdr.py`
(importa `app.cerebro.catalogo` e `app.cerebro.travas`, sem chamar API). Resultado: **OK**.

- **Frases de troca** (lidas de `papeis.<destino>.mensagem_troca` do snapshot), todas idênticas:
  - closer: 7x no novo.
  - periododegraca: 3x.
  - desqualificado: 2x.
  - O 2º balão "Posso te explicar como funciona o Auxílio-Acidente?" aparece 6x.
  - A mensagem exata de "APÓS DESQUALIFICAR" está igual.
  - A abertura, a pergunta do advogado, a mensagem da ética e o endereço continuam literais.
- **Passagem com o motor:** para os balões de cada destino, `tem_frase` e `transferencia_pela_frase` reconhecem o
  destino, e `frase_de_outro_destino` não acusa nada.
- **Links:** os 10 do fiel estão no novo, nenhum a mais (PTV.mp4, o áudio do Como Funciona, os dois áudios do
  endereço, o áudio da objeção e as 5 redes). Os dados do escritório (CNPJ, e-mail, as duas OAB) estão lá.
- **Promessa:**
  - "garant" aparece 1 vez, numa linha de proibição.
  - `garantia_de_resultado` não acha nada fora de negação.
  - "terá direito a receber" não existe mais.
  - Estes textos que o roteiro manda escrever passam por `catalogo.conferir` (trava de produção) sem erro:
    - os balões do closer;
    - a frase do período de graça;
    - a mensagem de desqualificação;
    - a 5.1, com um "?";
    - as respostas prontas a dúvidas;
    - a passagem do advogado.
- **Motor:** `ferramentas_do_prompt` lê os mesmos destinos do fiel (`closer`, `periododegraca`, `desqualificado`) e
  nenhuma ação. O `montar_sistema` monta sem erro (≈39,8 mil caracteres com o FORMATO).
- **Seções:** os 47 títulos do fiel estão no novo. Só o da pergunta 2 mudou, de propósito.

## Pendências (decisão do escritório; não mudei)

- **"Já tentou e foi negado".** Contradição interna:
  - TRAVAS: "→ DESQUALIFICADO".
  - OBJ 9: "Isso é comum... Quer seguir?".
  - Nenhum cenário testa esse caso. É regra de negócio.
- **OBJ 1: "O maior risco é continuar sem receber um direito seu".** Afirma o direito. A trava não barra, e o texto das
  objeções ficou idêntico por regra. Sugestão: "deixar de pedir um benefício que pode ser seu".
- **CONDUTA: "informar ao cliente que os valores podem variar".** A frase está incompleta e choca com "PROIBIDO informar
  valores". Não apareceu como erro.
- **"período de graça" na 5.1.** O termo é do escritório e ficou. A trava completa (`TERMOS_PROIBIDOS`) o contaria na
  métrica sombra, mas a trava do catálogo não barra.
- **Advogado + frase do desqualificado.** Ver item 18. A opção `inserir_frase_de_troca: false` em
  `papeis.desqualificado` muda todas as desqualificações. Não mexi na config.


## Corretor, rodada 1 (2026-11-25)

Mudanças mínimas pedidas pela revisão. Frases de troca (mensagem_troca), links de mídia e dados do escritório intactos.

- **[0] Casos especiais da Tool `periododegraca` x perguntas 2 e 4.** Confirmado: o gatilho "incerteza sobre datas do acidente" e o "(antes, durante ou depois)" mandavam ao PG quem não lembrava o ano (contra "não saber a data não desqualifica... siga para a pergunta 3") e quem era CLT "durante" (contra "CLT SIM → closer").
  - A seção agora abre com: "Só vale depois das perguntas 2, 3 e 4 respondidas (perguntadas por você ou já ditas pelo lead)."
  - Gatilho de incerteza.
    - ANTES: "incerteza sobre datas do acidente ou do vínculo CLT ... 'não lembro o ano exato'".
    - DEPOIS: incerteza sobre as datas do VÍNCULO CLT, depois de a pergunta 4 ter sido respondida com NÃO ou "não sei". Acrescentado: "Não saber a data do ACIDENTE não é gatilho".
  - Vínculo próximo ao acidente.
    - ANTES: "(antes, durante ou depois)".
    - DEPOIS: "(antes ou depois, sem estar registrado na data)".
  - Exemplos de gatilho:
    - "Não lembro se foi em 94 ou 95" → "Não lembro se saí da firma em 94 ou 95".
    - "Faz muitos anos, não sei a data exata" → "Faz muitos anos que saí, não sei a data exata".
- **[1] Conciliação com o FORMATO do motor ("Você comentou que...").** Confirmado: catalogo.py l.285-287 bate com "NADA antes da frase".
  - Nova regra em "Regras desta resposta": a citação vale só quando a IA pula uma pergunta no meio do roteiro, e deve ser curta, sem datas, números nem nome de empresa.
  - Na resposta de passagem não se cita nada: a frase de passagem é o 1º balão.
- **[3] Cliente antigo.** Confirmado: o sinal confirmado pausa o lead antes do agente (turno.py). Com "o sistema avisa a equipe sozinho. Não continue o fluxo.", o lead ficava sem resposta e sem nenhuma pessoa da equipe.
  - DEPOIS: "e você está respondendo → preencha "notificacao": "analise_humana" e escreva só: "Vou pedir para a nossa equipe conferir o seu cadastro e retornamos por aqui."".
  - A seção SISTEMA DE NOTIFICAÇÃO ganhou uma frase que aponta para essa regra. O SDR tem `notificacao: true`.
- **[5] "Já tentei e negaram".** Confirmado: o SDR tinha trava de desqualificação, enquanto a OBJ 9 do SDR, do Closer, do Contratos e do PG trata o caso como objeção.
  - Escolhi o caminho (a), o único que mantém as objeções das quatro etapas: pedido negado não desqualifica.
  - A trava virou: "NÃO desqualifica e não é gatilho da pergunta do advogado: OBJ 9 sem a pergunta final + pergunta pendente".
  - "no INSS" saiu dos gatilhos do advogado: "pedi no INSS e negaram", sozinho, não é gatilho.
  - No Desqualificado, saiu a linha do motivo "negado".
  - **Decisão do escritório a confirmar.** Se o escritório quiser desqualificar quem teve o pedido negado, o caminho é tirar a OBJ 9 das quatro etapas.
- **[6] OBJ 1 e OBJ 7 iguais nas quatro etapas.** Confirmado.
  - ANTES: "O maior risco é continuar sem receber um direito seu." / "Quem inicia cedo recebe cedo."
  - DEPOIS (igual ao Closer e ao PG): "O maior risco é deixar o tempo passar sem fazer o pedido." / "Quem inicia cedo resolve mais cedo."
  - Motivo: no SDR o lead ainda não foi qualificado. "Um direito seu" afirmava o direito a quem pode ser desqualificado dois turnos depois.
  - Isso também resolve a pendência "OBJ 1" anotada acima.
  - O item [17] da revisão pedia o contrário: voltar ao texto antigo no Closer e no PG. Não apliquei, porque o texto antigo afirma direito e recebimento, e a regra "nada de promessa" pesa mais. Troca a aprovar pelo escritório.
- **[8] Pergunta 2: "feita" x "respondida".** Confirmado.
  - Onde: nas regras da pergunta 2, no SIM da pergunta 4, em REGRAS PARA QUALIFICAR e na Tool `closer`.
  - "Feita/perguntada" virou "respondida (perguntada por você ou já dita pelo lead)".
  - Assim, quem conta a data no relato não é perguntado de novo só para cumprir a exigência.
- **[16] "Sou MEI" no presente.** Confirmado: contradizia "MEI paralelo não importa" e a regra dos tempos verbais.
  - "Respostas que JÁ CONTAM" agora só aceita respostas sobre a época: "trabalhava por conta", "era autônomo", "na época era MEI", "era MEI quando aconteceu".
  - "Sou MEI", no presente, não conta: a IA faz a pergunta 4 normalmente.
  - O sc15 continua passando: o cartão responde à pergunta 4 com "nao, na epoca eu ja trabalhava por conta".
