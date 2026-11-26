# Contratos: o que mudou e por quê

Instrução nova: `contratos.md`, para colar em `etapas[codigo=contratos].instrucao` do snapshot `sousa_costa.json`. A `mensagem_troca` de Contratos ("Excelente! Por gentileza, me informe seu nome completo para darmos continuidade à formalização.") não muda e aparece citada, igual, no CONTEXTO. Contratos não tem `boas_vindas` nem destinos. Objeções, links de mídia, redes, CNPJ, OAB e endereço do escritório estão iguais ao snapshot fiel (conferido por script).

Rodadas lidas: 0317 e 0426 (snapshot fiel) e 0523 (com a 1ª leva, `sousa_costa_sugerido.json`).

## Por que o gpt-4.1-mini (temperatura 0.5) ainda errou com a 1ª leva

1. **Regra "só se não informou" escrita entre parênteses, dentro de um roteiro em passos.** A seção "REGRA DE REFORÇO (PRIORIDADE MÁXIMA)… sobrescreve qualquer outra instrução" lista "Perguntar o Número / Perguntar o Complemento" como passos fixos. O modelo segue os passos e ignora o parêntese. A conferência de DADOS JÁ INFORMADOS precisa ser a primeira instrução, com exemplos do que conta como "já respondido".
2. **Lacuna, não desobediência.** Nada no prompt dizia o que responder sobre lesão nova, documentos médicos, prazo ou impressão. Sem texto, o modelo improvisa ("podemos incluir sim", "pode levar alguns meses").
3. **O prompt falava de um sistema que não existe mais.** Ele mandava "acionar tool `buscarcep`" e dizia que o CPF só é conferido "quando gera o contrato". Hoje o motor busca o CEP e confere o CPF no mesmo turno e escreve linhas "(sistema)" que o prompt nunca citava. O modelo não ligava essas linhas ao roteiro.
4. **A 1ª leva trocou a pergunta final por "Confere se está tudo certo…".** O texto saiu do padrão `posso gerar o contrato|está tudo correto`, e sc01 e sc03 da 0523 reprovaram em `faltou_obrigatorio`.

## Mudanças

1. **Bloco "O QUE O SISTEMA FAZ POR VOCÊ" (novo, logo depois do CONTEXTO)**
   - Problema: CPF válido chamado de "incorreto" (sc01 e sc10 da 0317, de T12 a T30); "Vou buscar os dados nos Correios" sem busca (sc02 0317, T16); endereço inventado (sc02 0317, T17).
   - ANTES: nenhuma menção a DADOS JÁ INFORMADOS, CONFERÊNCIA DO CPF, BUSCA DE CEP nem FATOS DO SISTEMA.
   - DEPOIS: lista curta do que cada linha traz, com os nomes dos campos (nome_completo, cpf, numero_casa, complemento, telefone_contrato…), e a regra: o campo que está ali não se pergunta de novo.
   - Por quê: as regras abaixo citam essas linhas pelo nome. O modelo precisa saber de antemão que elas são a fonte da verdade.

2. **Frase da passagem e lead que fala por outra pessoa (CONTEXTO)**
   - Problema: risco de repetir o pedido do nome que o Closer já fez; sc03 (esposa pelo marido) misturava "seu" e "dele".
   - ANTES: nada.
   - DEPOIS: cita a `mensagem_troca` exata com "não repita essa frase"; os dados do contrato são os do acidentado ("o CPF dele").
   - Por quê: a primeira mensagem do lead nesta etapa já é a resposta ao nome.

3. **Conferência antes de cada pergunta + dúvida junto com dado (Interpretação Automática)**
   - Problema: número 418 mandado junto com o CEP e pedido de novo (sc03 0426, T22: "como eu falei, mandei ali em cima, é 418"); telefone pedido de novo quando veio junto com uma pergunta (sc03 0523, T23); pergunta "o escritório fica onde?" ignorada (sc03 0523, T19).
   - ANTES: "Separar tudo internamente → Registrar → Perguntar apenas o que faltar".
   - DEPOIS: conferir DADOS JÁ INFORMADOS e todas as falas do lead antes de cada pergunta; "como eu falei" é sinal de erro e pede para pegar o dado do histórico. Dado junto com dúvida: registrar, responder pelo roteiro e terminar com a pergunta do próximo campo, numa resposta com uma pergunta só.
   - Por quê: transforma o "não repita" em um passo concreto, que é o que o 4.1-mini segue. Alinha com o FORMATO do motor ("responda e retome a pergunta pendente").

4. **Vídeo PedidoDocumento.mp4: quando e como**
   - Problema: o link foi dentro de um texto com pergunta (sc01 0523, T16); saiu depois do pedido de CEP (sc11 0426); não saiu nunca (sc02 e sc03 0523).
   - ANTES: "Ao iniciar o pedido de dados, envie SOMENTE este link 1 VEZ".
   - DEPOIS: o mesmo texto e o mesmo link, mais "na sua PRIMEIRA resposta nesta etapa (a que responde ao nome), num balão só com o link puro… depois a pergunta do CPF".
   - Por quê: "ao iniciar o pedido de dados" era ambíguo, porque o pedido do nome sai na passagem do Closer. O motor só manda como mídia um balão que é só o link.

5. **Tolerância de formato: CPF e RG**
   - Problema: "o último grupo deve ter dois dígitos" em laço (sc10 0317); CPF chamado de "formato incorreto" (sc10 0317, T15).
   - ANTES: só CEP e Telefone (a 1ª leva acrescentou CPF e RG sem exemplo).
   - DEPOIS: CPF e RG com exemplos reais ("057.830.862.23", "MG-14.207.385", "27.519.044 81") e "pontuação nunca é erro". Estado escrito por extenso vira sigla (MG), e estado civil com erro de digitação vale.
   - Por quê: com o exemplo, o modelo para de comparar o dado com o "123.456.789-00" das regras do zapsign. A sigla também evita o pedido "o seu estado (a sigla)" que o sistema fez no sc03 0426.

6. **ENDEREÇO: buscar CEP passa a ser automático**
   - Problema: "Recebi seu CEP… Vou buscar os dados…" sem pergunta (sc02 0317, T16 e T24); `ferramenta: buscar_cep` marcada à toa (sc03 0523, T19; sc11 0426).
   - ANTES: "Pergunte ao lead seu CEP. Depois acionar tool `buscarcep`. Se Sim… Se Não…".
   - DEPOIS: "o sistema busca sozinho e escreve a linha BUSCA DE CEP (sistema)", com um caso para cada resposta possível dessa linha: encontrado, não encontrado, CEP geral e fora do ar.
   - Por quê: são os mesmos textos que o motor escreve (`_linha_da_busca_de_cep`), então o modelo casa a regra com a linha que recebe.

7. **"Buscamos nos Correios" só com a linha da busca**
   - Problema: endereço digitado pelo lead apresentado como resultado dos Correios (sc11 0426, T17; reprovado por `buscamos nos correios`); cidade trocada por "Minas Gerais, MG" (sc03 0523, T19).
   - ANTES: "Envie 'Buscamos nos Correios e o seu endereço é: [ENDEREÇO BUSCADO]'".
   - DEPOIS: copiar rua, bairro e cidade/UF EXATAMENTE da linha "encontrado". Sem essa linha, não houve busca. Endereço digitado pelo lead vira "Anotei seu endereço: …" e nunca cita os Correios. Correção do lead vale.
   - Por quê: tira a fonte da micro-alucinação e evita a trava `endereco_sem_fonte` do motor.

8. **Número e complemento na mesma mensagem**
   - Problema: "Número 318 Fundos Correto" gerou o pedido do complemento 3 vezes e depois "o complemento é 'Fundos', certo?" (sc02 0426, T17-19; 0523, T17-19). O contrato saiu sem complemento (sc02 0523). "318, é casa" e "06 / Casa" foram tratados como incompletos.
   - ANTES: "Pergunte o número e complemento caso tenho (só o que o lead ainda não informou)".
   - DEPOIS: regra "NÚMERO E COMPLEMENTO JUNTOS" com os exemplos que apareceram nos testes ("Número 318 Fundos" → 318 + Fundos; "correto"/"isso" soltos não mudam nada; "não tem" → não possui).
   - Por quê: o modelo não sabia separar as duas partes e, na dúvida, perguntava de novo. Com o exemplo literal do caso, a separação vira cópia.

9. **Nada de confirmar dado isolado nem repetir o nome**
   - Problema: "Entendi que o complemento é 'Fundos'. Se estiver correto…" (sc02 0523, T19); "o telefone é o mesmo do WhatsApp, certo?" (sc02 0426); "Obrigado pelo RG, Valdir Santana Rocha" a cada turno.
   - ANTES: "Nunca confirmar dados isolados".
   - DEPOIS: a mesma regra com as formas proibidas por extenso ("certo?", "correto?", "se estiver correto, seguimos", o dado repetido como pergunta) e "não repita o dado nem o nome do lead a cada resposta".
   - Por quê: a regra genérica não pegava as paráfrases. Os exemplos são exatamente o que o modelo escreveu.

10. **Exceções ao "nunca solicitar reenvio"**
    - Problema: o modelo pedia reenvio do CPF por formato e do CEP em laço.
    - ANTES: "Nunca solicitar reenvio" (sem exceção, mas o resto do prompt mandava pedir).
    - DEPOIS: as duas exceções, uma vez cada: CPF com a linha INVÁLIDO e CEP com a linha "não encontrado".
    - Por quê: tira a contradição interna. Com ela, o modelo escolhia o lado errado.

11. **CEP entra na lista de CAMPOS OBRIGATÓRIOS; o "9." vazio sai**
    - Problema: a lista ia de "Estado civil" para "Número do imóvel", sem o CEP, e terminava num "9." vazio.
    - ANTES: 1 Nome, 2 CPF, 3 RG, 4 Estado civil, 5 Número, 6 Complemento, 7 E-mail, 8 Telefone, 9 (vazio).
    - DEPOIS: 1 Nome, 2 CPF, 3 RG, 4 Estado civil, 5 CEP, 6 Número, 7 Complemento, 8 E-mail, 9 Telefone, e "cada campo é perguntado UMA vez".
    - Por quê: é a ordem que o próprio modelo já seguia nas três rodadas. Agora ela está escrita.

12. **Telefone "esse mesmo do zap"**
    - Problema: o lead respondeu "pode ser esse mesmo do zap" e o modelo pediu "o número completo com DDD" (sc02 0426); na confirmação saiu "Telefone: não informado" (sc02 0426, T22).
    - ANTES: nada.
    - DEPOIS: subseção Telefone. "Do zap" é resposta: usar o telefone de FATOS DO SISTEMA e nunca pedir os dígitos.
    - Por quê: o motor já põe o telefone do WhatsApp em FATOS DO SISTEMA, e o contrato usa esse número quando falta o `telefone_contrato`.

13. **E-mail: dois e-mails**
    - Problema: sc03 mandou dois e-mails ("usa esse outro").
    - ANTES: nada.
    - DEPOIS: "use o último que ele indicar". "Sem problema, seguimos sem." continua igual (obrigatório do sc10).

14. **CPF ligado à CONFERÊNCIA DO CPF (sistema)**
    - Problema: CPF válido chamado de "incorreto" em laço (sc01 e sc10 0317).
    - ANTES: "Não há consulta de CPF nesta etapa: o sistema confere… quando gera o contrato. Se o sistema avisar que o CPF está errado, peça novamente…".
    - DEPOIS: três casos ligados ao texto da linha do motor: VÁLIDO (não comente), INVÁLIDO (peça uma vez, "os números não conferem", até 200 caracteres) e "segue pendente" (não insista). Sem a linha, nunca dizer que está errado.
    - Por quê: o texto antigo plantava a ideia de um aviso de erro que o modelo inventava. Agora a decisão é só da linha.

15. **LESÃO OU SEQUELA NOVA (seção nova)**
    - Problema: "podemos incluir sim, desde que tenha relação" (sc03 0523, T14 e T23); "vamos incluir isso na avaliação" (sc03 0426, reprovado como promessa crítica); "podemos avaliar para incluir no processo, sim" (sc02 0523, T20); "Vamos incluir essa sequela… para garantir o direito dele" (sc03 0317).
    - ANTES: nada (só "Prometer resultado").
    - DEPOIS: frase fixa "Anotei aqui. O advogado avalia tudo isso na análise do seu caso." mais a próxima pergunta, e a lista do que nunca responder.
    - Por quê: aconteceu em todas as rodadas por falta de texto. A frase foi testada contra os proibidos de todos os cenários e contra as travas de produção.

16. **Documentos médicos, prazo e impressão (seção nova)**
    - Problema: no Closer, "preciso dos documentos… laudos" (sc03 0523, T13); na Assinatura, "pode levar alguns meses" (sc02 0523, T25). As duas perguntas também aparecem no meio da coleta.
    - ANTES: "Falar sobre documentação" (proibido), sem dizer o que responder.
    - DEPOIS: uma resposta neutra para cada caso, mais "siga a coleta". A resposta a documento médico não pede nem dispensa documento, porque "não precisa de laudo" também é proibido no sc02.
    - Por quê: dá saída ao modelo, sem promessa nem prazo, e mantém a condução.

17. **Proibições explícitas em LIMITES LEGAIS**
    - Problema: "garantir seu direito/benefício/o melhor resultado" (Closer, Assinatura, Contratos), prazos inventados e pedido de laudo.
    - ANTES: "Prometer resultado…".
    - DEPOIS: mais 4 linhas: não pedir documentos; não usar "garantir/garantia/garantido", "você tem direito" nem "você vai receber o benefício/os atrasados"; não dizer que lesão nova entra; não dar prazo.
    - Por quê: são as expressões que as travas barram. Repetidas 2x, elas pausam o lead.

18. **Confirmação final: abertura sem "garantir", uma pergunta só e tudo na mesma resposta**
    - Problema: 3 "?" na mesma resposta (sc02, sc03 e sc11 em 0317/0426); a abertura saiu sozinha num turno e a lista no outro (sc03 0426, T25-26); pergunta da 1ª leva fora do padrão (sc01 e sc03 0523, `faltou_obrigatorio`); "Número: 318 Fundos / Complemento: Fundos" (sc02 0523).
    - ANTES: "…para garantir que está tudo certinho, tudo bem?" + dados + "Está tudo correto? Posso gerar o contrato?"
    - DEPOIS: "Vamos confirmar juntos todos os seus dados para ver se está tudo certinho." + lista com um campo por linha (Número só com o número, Complemento separado, UF em sigla) + "Está tudo correto para eu gerar o contrato?", os três na MESMA resposta.
    - Por quê: fica uma pergunta só. "está tudo correto" atende aos obrigatórios do sc01 e do sc03. Sem "garantir", o prompt não ensina mais a palavra que a trava barra.

19. **O que conta como "sim"**
    - Problema: "agora sim, pode gerar" diante só da abertura, sem a lista (sc03 0426, T26), e o zapsign foi acionado no mesmo turno.
    - ANTES: "Caso o Lead mande uma mensagem afirmativa".
    - DEPOIS: só vale o "sim" dado depois da mensagem com a lista e a pergunta. Sem isso, enviar os 3 passos.
    - Por quê: zapsign só depois da confirmação de verdade.

20. **ETAPA 3: zapsign pelo campo "ferramenta" e mensagem obrigatória sem prazo**
    - Problema: "Em alguns segundos você vai receber o link" saiu também quando o sistema, em vez do link, pediu um dado (sc02 0317, T23); o FORMATO do motor manda não dizer que o link chega em instantes.
    - ANTES: "Acionar **Tool `zapsign`**" e "Perfeito! Estamos gerando o seu contrato. / Em alguns segundos você vai receber o link para assinatura!".
    - DEPOIS: "Preencha "ferramenta": "zapsign" apenas 1 vez", na mesma resposta da mensagem "Perfeito! Estamos gerando o seu contrato.", sem escrever link. Quando o sistema pede a correção de um dado: recebido o dado, acionar o zapsign de novo sem refazer perguntas. As 10 frases de espera continuam, só para quando o sistema não pediu nada.
    - Por quê: não briga com o motor, que confere os dados, manda o link ou pede a correção, e trata o laço de correção (`_correcao_repetida`).

21. **Endereço do escritório no meio da coleta**
    - Problema: pergunta ignorada (sc03 0523, T19). Quando a pergunta foi respondida, o "Conseguiu entender direitinho?" mais o campo pendente geraram "como eu falei, entendi sim" e uma pergunta repetida (sc03 0426).
    - ANTES: link `enderecosemfalar.ogg` + "Conseguiu entender direitinho?".
    - DEPOIS: o mesmo link e a mesma frase fora da coleta. No meio da coleta, a pergunta do próximo campo entra no lugar de "Conseguiu entender direitinho?", com uma pergunta só.
    - Por quê: a dúvida é respondida e a condução é retomada na mesma resposta.

22. **Objeção no meio da coleta**
    - Problema: risco de 2 perguntas (a da objeção e a do campo) ou de reiniciar a coleta depois do "sim".
    - ANTES: nada.
    - DEPOIS: a objeção termina com a pergunta dela; depois do aceite, volta ao próximo campo que falta. "Dados do escritório" = nome, CNPJ, OAB e Instagram, num balão separado. O texto das OBJ 1 a 11 não mudou.

23. **REGRA DE REFORÇO (nome e endereço)**
    - Problema: a seção "sobrescreve qualquer outra instrução" e, por isso, também passava por cima do "não pergunte de novo" (achado do sc03 0426, T22).
    - ANTES: passos fixos com "Acionar a tool `buscarcep`".
    - DEPOIS: a mesma estrutura (1, 2, 3a, 3b, 3c, bloqueio) com "ela nunca autoriza perguntar de novo um dado já informado"; o passo 2 diz que a busca é do sistema; o 3c tem a saída para o lead que insiste no CEP ou digita o endereço; nome junto com pergunta conta como recebido, e a correção do nome vale.
    - Por quê: a prioridade máxima continua valendo para não gerar contrato incompleto, sem virar licença para repetir perguntas.

24. **Regras da ferramenta zapsign e balões**
    - ANTES: "descrição da tool no n8n… `buscarcep` só 1 vez"; "Dividir mensagens com \n\n".
    - DEPOIS: "o sistema formata sozinho; servem para conferir a lista"; a busca é feita pelo sistema; cada item de "mensagens" é um balão e o link fica sozinho no balão dele.
    - Por quê: é o formato de saída do nosso motor.

## O que ficou igual de propósito

- Os textos das OBJ 1 a 11, incluindo "O maior risco é continuar sem receber um direito seu." e "Quem inicia cedo recebe cedo." (pela restrição de manter as objeções). Nenhuma das duas é barrada pelas travas de produção, porque nenhuma traz uma expressão de certeza junto. Se o escritório topar, vale trocar depois.
- Credibilidade, CNPJ, OAB, endereço do escritório, links de áudio e vídeo, o PTV.mp4 proibido, presencial em BH, videochamada e SISTEMA DE NOTIFICAÇÃO.

## Conferência feita (script, sem chamar a API)

- `mensagem_troca` de Contratos citada idêntica. Nenhuma frase de troca de outro papel no texto, então o motor não lê transferência. `ferramentas_do_prompt` não tira destino nem ação do texto.
- 10 de 10 links do snapshot fiel preservados, sem link novo.
- "garant" só aparece na linha que proíbe a palavra.
- Bloco de objeções idêntico ao do fiel; CNPJ, OAB e endereço presentes.
- As frases fixas novas passam nas travas de produção (`catalogo.conferir`) e nos proibidos de todos os cenários, com uma exceção esperada: a frase do CPF INVÁLIDO casa com o proibido do sc20, cujo CPF é válido. Ela só pode sair com a linha INVÁLIDO do sistema.
- Os obrigatórios de contratos (sc01, sc03, sc10) têm o texto no roteiro.
- O sistema do papel monta sem erro (29,4 mil caracteres; a instrução foi de 15,2 mil para 26,1 mil).
- Não verificado: comportamento real com o gpt-4.1-mini (a bateria não foi rodada).


## Corretor, rodada 1 (2026-11-25)

Mudanças mínimas pedidas pela revisão. Frases de troca (mensagem_troca), links de mídia e dados do escritório intactos.

- **[4] Frases de espera sem prazo e sem promessa de link.** Confirmado.
  - O Contratos só recebe mensagem depois do zapsign quando o contrato NÃO saiu (equipe_envia, imprevisto ou correção).
  - "Em breve te envio o link", "Já já te mando o link" e "Só mais um instante" contradiziam o FORMATO do zapsign e o "Dar prazo" do NÃO PODE.
  - A lista de 10 frases ficou com 3: "Seu contrato está em preparação.", "Estamos finalizando os detalhes do seu contrato." e "Assim que ele estiver pronto, o link chega aqui na conversa.".
  - Regra nova: se o sistema já avisou que a equipe vai enviar o contrato (ou que deu imprevisto), a IA não fala de prazo nem de link. Diz só "Nossa equipe dá sequência por aqui.".
- **[6] OBJ 1 e OBJ 7 iguais às do Closer e do PG.**
  - ANTES: "O maior risco é continuar sem receber um direito seu." / "Quem inicia cedo recebe cedo."
  - DEPOIS: "O maior risco é deixar o tempo passar sem fazer o pedido." / "Quem inicia cedo resolve mais cedo."
  - Isso substitui a decisão anterior de manter o texto antigo.
- **[10] Campo sem resposta.** Confirmado: "Cada campo é perguntado UMA vez" e "e-mail uma única vez" não diziam o que fazer quando o lead mudava de assunto.
  - Regra geral.
    - ANTES: "Cada campo é perguntado UMA vez. Se já está em DADOS JÁ INFORMADOS ou na conversa, pule."
    - DEPOIS: "Campo RESPONDIDO não se pergunta de novo [...] Se o lead não respondeu (mudou de assunto, corrigiu outro dado ou fez uma pergunta), responda e, na mesma resposta, refaça a mesma pergunta uma vez."
  - E-mail: "uma única vez; se o lead não respondeu (falou de outro assunto), refaça uma vez depois de atender o outro assunto."
  - LESÃO OU SEQUELA NOVA.
    - ANTES: "pergunte o próximo campo que falta".
    - DEPOIS: "pergunte o campo que ficou sem resposta (refeita uma vez, mesmo que seja o e-mail) ou, se nada ficou pendente, o próximo campo que falta".
  - O CPF entrou no bloqueio absoluto do zapsign.
- **[11] "Onde fica o escritório?" no meio da coleta.** Confirmado.
  - Na regra do endereço, acrescentado: "Pergunta de onde fica o escritório ou qual o endereço segue só esta regra (áudio + próximo campo), não a OBJ 2. A OBJ 2 vale só para quem pede atendimento presencial."
  - Regra 6 da ETAPA 6: os dados vão na mesma resposta, ANTES da pergunta final, como no Closer.
