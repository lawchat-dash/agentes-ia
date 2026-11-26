# Síntese: bateria REAL de 2026-11-25_0017 (agente de referência)

Observação: o texto que recebi foi cortado no meio do grupo 03 e não trouxe as análises de 04 e 05. Para esses pontos li as transcrições, `resultado.json`, os cenários e o código. Nada foi editado e a API não foi chamada.

## 1. Veredito real por cenário

| Cenário | Placar do teste | O agente está... | Por quê |
|---|---|---|---|
| 01_viavel_ate_assinatura | 0/3 | **Bom, com 2 deslizes** | R1 e R3 travaram porque o lead simulado não reconhece "Quer que a gente **siga**" nem "Está tudo **correto**". Ficou 17 turnos em "não sei te dizer". A R2 fechou o contrato. Os erros reais: na R2 t9 o closer pediu o nome completo depois de um "não sei", e o agente refaz respostas na trava com frequência. |
| 02_desqualificado_sem_qualidade | 0/3 | **Bom** | Chegou ao destino certo nas 3 rodadas e não revelou regra interna. Os "vazamentos" são as perguntas que o roteiro manda fazer. O pulou_pergunta vem do oráculo: aposentado e advogado não mudam o destino desqualificado. Fica um risco escondido no prompt (ver item 4 dos erros). |
| 03_periodo_de_graca [com/sem seguro] | 0/3 e 0/3 | **Ruim** | O Período de Graça pergunta de novo a data que a lead já tinha dado ("demitida em janeiro de 2023", R1 t4 → t5). Quando ela reclama ("já te falei isso"), uma reclamação só pausa a conversa (frase fixa de sinal). Isso acontece porque o auditor está desligado no cenário. |
| 04_objecao_golpe | 2/3 | **Bom nas objeções, ruim no contrato sem e-mail** | Tratou bem golpe, CPF e link. Na R1, a lead disse "não tenho e-mail" e o zapsign foi chamado 4 vezes (t27–t30). Em cada uma o sistema pediu o e-mail de novo, e a IA prometeu "o link chega em instantes" 4 vezes sem link nenhum. |
| 05_lead_audio | 1/3 | **Bom** | Entende bem áudio e imagem. R2 e R3 travaram na regex do aceite ("Você **gostaria de seguir**", "Quer que a gente **siga**"). Na R3, "Você já **se aposentou**?" não casa com `aposentad`, então o lead nunca respondeu. A IA passou ao closer sem essa resposta, um deslize pequeno. Na R2, a pausa veio depois de 4 "não sei" e 1 "já te falei" com o auditor desligado. |
| 06_fora_do_roteiro | 0/3 | **Ruim** | Nas 3 rodadas, o pedido do link do site (t5) foi barrado duas vezes pela trava de promessa, e o lead ficou pausado. Por isso a fala 6 nunca rodou. O "garantir que você seja bem atendido" é falso alarme. |

## 2. Erros reais do agente, por impacto no lead

1. **Uma pergunta inocente pausa o atendimento (06, 3/3; refações em 01 e 05).** Ninguém responde o lead, que fica esperando a equipe por causa de uma pergunta sobre o site. A causa provável é o "Atendimento **100% online** pelo WhatsApp" dos dados do escritório, que `travas.CEM_POR_CENTO` barra como promessa. O "com certeza" em `PROMESSAS` também pode disparar. A causa é inferida: o texto barrado não fica gravado. Há indícios: a versão refeita traz "cuida de tudo online" (01 R1 t12, 05 R3 t10), e a R2 do 01, que não teve refação, não usou essa frase. Além disso, a orientação genérica de `catalogo.conferir` não diz o que caiu, e a 2ª tentativa erra de novo.
   - `app/cerebro/turno.py`, `_turno_catalogo` (~l.309): gravar cada tentativa e o texto reprovado (`saida.contexto.setdefault('tentativas', []).append(...)` e `texto` em `saida.reprovacoes`) em vez de sobrescrever. Fazer isso **antes** de tudo, para confirmar o gatilho.
   - `app/cerebro/travas.py`, `CEM_POR_CENTO`: lookahead negativo para `online|on-line|digital|pelo whatsapp|via whatsapp|a dist[aâ]ncia`. **Não** isentar "gratuito" nem "sem custo", porque o escritório cobra 30%. Em `PROMESSAS`, trocar "com certeza", "certeza que" e "certeza de que" por formas ligadas a resultado ("com certeza vai", "certeza que vai", "certeza de que vai").
   - `app/cerebro/catalogo.py`, `conferir()` (l.283–284): citar o trecho que casou, com `next((p for p in PROMESSAS if normalizar(p) in normal), None)` ou o match de `CEM_POR_CENTO`. Escrever "Reescreva sem a expressão '<trecho>'" e não falar em "resultado".
   - Testes em `tests/`: "Nosso atendimento é 100% online pelo WhatsApp" e "Claro, com certeza! O atendimento é por aqui" passam. "100% de chance" e "100% garantido" continuam barrados.

2. **Um lead sem e-mail entra em laço e recebe uma promessa falsa de link (04 R1).** `app/contrato/dados.py` (~l.164) só acusa `erro("email")` quando o campo tem algo que não é e-mail. O extrator gravou um texto ("não tenho" ou parecido; o valor é inferido) em `email`. O zapsign volta com "preciso confirmar o seu e-mail" e a IA chama de novo sem nenhum dado novo. Na R2 e na R3, com o campo vazio, deu certo.
   - `app/contrato/dados.py`: e-mail inválido e não obrigatório vira vazio (`d.pop("email")`), sem erro.
   - `app/cerebro/extrator.py` (~l.94): "email só se tiver @; 'não tenho' = deixar vazio".
   - Motor/zapsign: se a mesma correção for pedida 2 vezes sem fato novo, não chamar de novo e passar para a equipe. A IA também não deve dizer "o link chega em instantes" antes do retorno da ferramenta.

3. **O Período de Graça repete uma pergunta já respondida, e uma reclamação vira pausa (03, 6/6).** A lead precisa repetir o que já disse e depois é largada.
   - `avaliacao/agentes/catalogo_referencia.json`, `et-periododegraca`, seção 2, e o prompt real no banco: "Antes de perguntar, leia a conversa e os DADOS JÁ INFORMADOS. Se a pessoa já disse quando saiu do emprego, use a data e vá para a pergunta 2. Se ela disser que já respondeu, peça desculpas e siga."
   - `app/cerebro/turno.py`: o rótulo passa a ser "DADOS JÁ INFORMADOS PELO LEAD (não pergunte de novo):".
   - `app/cerebro/sinais.py`, `guia_do_extrator` (linha do `muitas_objecoes`, ~l.50) e `PARTES_DO_AUDITOR['muitas_objecoes']`: "Reclamar que a atendente repetiu ('já te falei', 'já respondi') NÃO é objeção."
   - O auditor de produção está ligado por padrão (`pipeline.py:739`) e provavelmente vetaria esse sinal. Mesmo assim o extrator está errado, e um escritório com auditor desligado sofre isso.

4. **O lead pode chegar ao closer sem a checagem de aposentadoria e advogado (risco escondido, visto em parte no 05 R3).** O SDR manda desempregados e autônomos ao Período de Graça antes das perguntas 3 a 5. O `# 3. DECISÃO` do `et-periododegraca` manda "Estava coberto: acionar `closer`" sem conferir sequela, aposentadoria nem advogado. Neste teste o destino saiu certo por acaso, porque todos foram desqualificados.
   - `catalogo_referencia.json`, `et-periododegraca` seção 3: "antes de acionar `closer`, confirme sequela, aposentadoria e advogado se ainda faltarem". Ou, no SDR: "periododegraca só depois das perguntas 3 a 5, salvo se uma já desqualificar".
   - Não pôr `aa.decidir_qualificacao` no motor genérico do catálogo. Se for preciso, só com `slug=='auxilio-acidente'` e destino `closer`.
   - No SDR: não transferir para o closer com uma pergunta do roteiro sem resposta (05 R3 t9).

5. **O closer trata "não sei" como aceite (01 R2 t8–t9).** A IA respondeu "Sem problemas... só preciso do seu nome completo" sem um sim. O comportamento é instável: na R1, na R3 e no 04 R1 isso não aconteceu.
   - `catalogo_referencia.json`, closer, seção 3: "Só acione `contratos` ou peça qualquer dado depois de um sim claro. 'Não sei' ou 'talvez' não é aceite: pergunte qual é a dúvida."

6. **A boas-vindas sai sem a primeira pergunta (t1 em 01, 02, 03 e 05 R3).** Um turno se perde, e a pergunta do lead ("tenho direito?") fica sem resposta.
   - `app/cerebro/turno.py` ~l.291: "comece com a boas-vindas e, na mesma resposta, faça a primeira pergunta do roteiro". Outra opção é pôr a pergunta na `boas_vindas` do SDR.

7. **Menores:**
   - Uma pergunta repetida com as opções conta como 2 (01 R2 t3, 05 R2 t1). Instrução do SDR, seção 4: "cada pergunta numa frase só, com as opções dentro".
   - O desqualificado começa com "Olá!" no meio da conversa (02 R2 e R3).

**Decidido contra o analista: "O que posso garantir é que cuidamos de todo o pedido" (01 R3 t19) não é violação.** A frase fala do serviço, não do resultado. **Não** amplie a trava de produção para o radical `garant`: isso traria mais refações e mais pausas como a do item 1. No máximo, acrescente ao prompt do closer: "evite a palavra garantir/garantia, mesmo para o serviço".

## 3. Ajustes no sistema de teste

1. **Regex de aceite e de confirmação** em `avaliacao/cenarios/01_viavel_ate_assinatura.json` (l.31 e 36), `04_objecao_golpe.json` (l.30 e 35) e `05_lead_audio.json` (l.31 e 36):
   - aceite: `(?i)\b(quer|podemos|vamos|posso|gostaria|deseja)\b.{0,30}\b(sig[ao]|seguir|prosseguir|continuar|dar (entrada|continuidade|andamento))|\btopa\b`
   - confirmação: `(?i)confer|confirm|(est[áa]|ficou) (tudo )?(cert|corret|ok)|pode(mos)? gerar|posso gerar|gerar o contrato`
2. **Lead simulado** (`app/avaliacao/leads.py`, LeadCartao):
   - (a) Depois de 3 respostas "padrão" seguidas, marcar a rodada como **inválida** ("lead sem assunto para: <pergunta>"), sem reprovar o agente.
   - (b) Quando só casar um assunto já usado, responder "como eu falei, <resposta original>" em vez de um "já te falei isso" seco. Esse texto empaca a conversa e dispara sinal.
   - (c) Gatilho `depois_de` não deve engolir uma pergunta real que esteja no mesmo balão: responder o assunto primeiro (02 R1 e 03 R1 t4/t5).
   - (d) Regex: `aposentad|aposentou` em 05 (e nos demais). Em 03, acrescentar um assunto `saiu do (seu )?[úu]ltimo emprego|pagou o inss` **antes** de `carteira`, com a data da demissão. Isso cobre também o sem_seguro R3 t5.
3. **Auditor desligado nos 6 cenários** (`"sobrescrever_config": {"auditor": false}`). Produção usa auditor por padrão. Ligar por padrão e manter desligado só em um cenário próprio de "extrator sozinho", dito na `descricao`.
4. **Vazamento** (`app/avaliacao/checagens.py`, `Regras._janelas_do_prompt` ~l.153–172):
   - Gerar janelas só das linhas sensíveis: "Regra interna", "acionar tool", "nunca deve ser dita", números com "meses", seção `# 3. DECISÃO`.
   - Pôr em `permitidas` o nome do escritório e o do agente.
   - Teste: a frase do 02 R1 t5 não pode acusar. Uma frase com 40 caracteres ou mais ("a cobertura dura até 12 meses depois da última contribuição") tem de acusar.
5. **Promessa**:
   - `checagens.PROMESSAS_AVALIACAO` (l.58–68): trocar `\bgarant` por uma regex ligada a resultado (garant… + ganhar/receber/benefício/aprovação/direito; "benefício garantido"; "garantia de aprovação").
   - Tirar `(?i)garant` de `esperado.proibido` nos cenários 01 a 06, ou trocá-lo pela mesma regex.
   - Ajustar `(?i)100 ?%` do proibido junto com a trava, para não reprovar "100% online".
6. **dado_fora_de_hora** (`checagens.py:242`): isentar só o turno que transfere para a etapa limite **com a frase** (`transferencia_pela_frase(...) == etapa_depois`). Incluir `\bnome completo\b` em `_DADO_PESSOAL`. Criar a checagem `aceite_antes_de_contratos`: a última fala do lead antes de contratos precisa ser o assunto de aceite. Ela pegaria o 01 R2.
7. **pulou_pergunta** (`app/avaliacao/oraculo.py`, `fatos_decisivos` l.95–113): um fato de domínio fechado só é decisivo se algum valor dele mudar o destino.
8. **Falhas em cascata**: `cep` e `fato_nao_capturado` não devem acusar quando a trajetória não passou por `contratos`, porque só inflam a lista.
9. **refeito_pela_trava** (`checagens.py:204`) e transcrição: mostrar o texto da 1ª tentativa, que depende da gravação descrita no item 1 dos erros.
10. **06**: dar `espera` à fala 6, ou contar todas as falas restantes em `_parou_antes_do_roteiro`. Hoje o estado_final "pausado" bate por coincidência.
11. `varias_perguntas`: manter como está (gravidade média, não reprova sozinha). A correção é no prompt.

## 4. O que fazer primeiro

1. **Observabilidade**: gravar o texto reprovado em `turno.py` e mostrá-lo na transcrição. Custa pouco e confirma o gatilho do erro nº 1.
2. **Trava de promessa** (`travas.py` e `catalogo.conferir`): é o único erro que hoje deixa um lead real sem resposta numa pergunta banal.
3. **Contrato sem e-mail** (`contrato/dados.py`, extrator e limite de nova chamada do zapsign): é laço com promessa falsa no passo final, onde está o dinheiro.
4. **Prompt**: Período de Graça sem pergunta repetida e com checagem de aposentadoria e advogado antes do closer; extrator e auditor sem sinal por "já te falei"; closer só com sim claro; boas-vindas com a primeira pergunta.
5. **Sistema de teste**: regex de aceite e confirmação, lead simulado (padrão→inválida, repetição realista, gatilho), auditor ligado, vazamento, promessa, oráculo. Sem isso, 01, 05 e boa parte do 02 seguem reprovando por falso alarme.
6. Rodar de novo no modo REAL. É de esperar que 01, 02, 04 e 05 passem a refletir o agente, e que 03 e 06 só passem depois dos itens 2 a 4.

Resumo honesto: dos 7 casos, o agente está bom em 4 (01, 02, 04 fora do e-mail, 05). As reprovações desses vêm sobretudo do teste. Há 3 problemas reais que afetam leads de verdade: a trava que pausa sem motivo, o laço do contrato sem e-mail, e a pergunta repetida no Período de Graça com pausa por uma reclamação só. Há ainda um risco no prompt que o teste atual não exercita: lead "dentro" do período de graça indo ao closer sem a checagem de aposentadoria e advogado.

Arquivos principais citados:
- C:/Users/joaov/OneDrive/Documentos/Projetos Claude/IA de atendimento/app/cerebro/travas.py
- C:/Users/joaov/OneDrive/Documentos/Projetos Claude/IA de atendimento/app/cerebro/catalogo.py
- C:/Users/joaov/OneDrive/Documentos/Projetos Claude/IA de atendimento/app/cerebro/turno.py
- C:/Users/joaov/OneDrive/Documentos/Projetos Claude/IA de atendimento/app/cerebro/sinais.py
- C:/Users/joaov/OneDrive/Documentos/Projetos Claude/IA de atendimento/app/contrato/dados.py
- C:/Users/joaov/OneDrive/Documentos/Projetos Claude/IA de atendimento/avaliacao/agentes/catalogo_referencia.json
- C:/Users/joaov/OneDrive/Documentos/Projetos Claude/IA de atendimento/app/avaliacao/checagens.py
- C:/Users/joaov/OneDrive/Documentos/Projetos Claude/IA de atendimento/app/avaliacao/oraculo.py
- C:/Users/joaov/OneDrive/Documentos/Projetos Claude/IA de atendimento/app/avaliacao/leads.py
- C:/Users/joaov/OneDrive/Documentos/Projetos Claude/IA de atendimento/avaliacao/cenarios/ (01 a 06)