# Mudanças no prompt do PERÍODO DE GRAÇA (papel `periododegraca`, para o NOSSO motor)

Arquivo pronto: `periododegraca.md`. É a instrução completa do papel e entra no `instrucao` da etapa
`et-periododegraca` do snapshot (`agente.etapas[codigo=periododegraca].instrucao`), no mesmo formato do texto atual.

**Os campos de `papeis.periododegraca` não mudam:**
- `mensagem_troca`: "Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?"
- `boas_vindas`: `null`
- `destinos`: `["closer", "desqualificado"]`
- `ferramentas`: `notificacao: true`, `calculadora: true`

**Base:** a instrução fiel (`sousa_costa.json`), com as trocas P1 a P8 de `sousa_costa_sugerido.json` e as ideias do
rascunho `n8n/02_PERIODO_DE_GRACA.txt`, traduzidas para o motor:
- a "tool `qualificado`" e a "tool `closer`" do n8n viram `transferir_para = "closer"`;
- a "Tool `Calculator`" vira a linha de cobertura dos FATOS DO SISTEMA;
- a saída para "não sei" usa `notificacao = "analise_humana"`, que o motor já aceita neste papel (`sinais.DO_AGENTE`,
  pausa + aviso).

Este arquivo **substitui** o `periododegraca.md` anterior desta pasta (rascunho de 10:21). Diferenças principais em
relação a ele:
- saíram os exemplos com as datas reais do cenário sc16 (03/2023 → 11/2024, 20 meses);
- a desqualificação passou a ser só a mensagem longa, sem explicação antes, igual ao SDR;
- entraram o roteiro de decisão "QUAL RESPOSTA MANDAR AGORA" e os exemplos JSON.

Rodadas citadas, todas em `avaliacao/resultados/`:
- **0317**: `2026-11-25_0317_agente-sousa-costa` (prompt fiel);
- **0426**: `_0426_agente-sousa-costa` (prompt fiel);
- **0523**: `_0523_agente-sousa-costa-sugerido` (já com P1 a P8).

---

## Por que o gpt-4.1-mini a 0.5 ainda erraria (e por que a 0523 não mostra)

**A 0523 não passou pelo Período de Graça.** O sc16 foi cortado pelo teto de custo. No sc15[nunca_clt], o SDR
desqualificou direto: no T5, a 1ª resposta dele foi barrada por usar a frase deste papel com
`transferir_para = "desqualificado"`. Por isso P1 a P8 **nunca foram medidas**. A análise abaixo junta os erros da 0317
e da 0426 (prompt fiel) com o que P1 a P8 deixaram de pé:

1. **"ORDEM FIXA" com a pergunta 1 igual à frase de troca.** O modelo recomeça a lista do zero a cada turno.
   - Reenvia a frase: 0317 sc14 T8 e sc15[nunca_clt] T5.
   - Pergunta de novo o que o lead disse ao SDR: 0317 sc16 T6/T7 e 0426 sc16 T7/T8.

   A sugerida não mexeu nisso.
2. **Regras de data que se contradizem e não têm saída.** A sugerida manteve juntas:
   - "Nunca aceitar apenas o ano", estendida também à data do acidente (P5);
   - "Refazer a pergunta até obter mês e ano";
   - a frase do BLOQUEIO "preciso do mês e do ano exatos", sem limite.

   A P7 só abria saída depois de **2** "não sei" e de mais uma aproximação, ou seja, até 4 vezes a mesma pergunta. O sc14
   da 0317 repetiu a frase do BLOQUEIO 3 vezes (T9 a T11).
3. **O prompt ensina a fazer conta.** "Faça as contas corretamente", "Calcular o prazo de forma precisa", o ALGORITMO e
   as FÓRMULAS repetem o hábito do n8n: anunciar e chamar a Calculator. Daí vêm:
   - "vou calcular" e parar: 0317 sc16 T9 nos dois casos; 0426 sem_seguro T10;
   - a conta escrita passo a passo, com a data de hoje no lugar da do acidente: 0317 teve_clt T10 "março de 2026 ... 32
     meses"; sc16 T10 "36 meses".

   A P8 pedia "mostre a conta em 1 frase", o que ainda chama número, e com a data do acidente faltando o número é
   inventado.
4. **"Após qualificação" do escritório põe a troca depois do "sim".** A ordem lá é: Maravilha, depois a pergunta,
   depois "Se SIM → closer", depois o áudio. Isso deixa o modelo em dúvida sobre quando transferir. Na 0426 com_seguro
   T9 ele colou a frase no fim de um parágrafo com 3 "?".
5. **"Após desqualificação" não tem texto.** "Informar de forma educada" deixa o modelo improvisar ("Infelizmente...
   não mantém a qualidade de segurado") e às vezes esquecer o `transferir_para`. Na 0426 sem_seguro, T11 e T12, foram
   dois turnos de decisão sem troca, com o lead repetindo "como eu falei".
6. **Nada liga as linhas do motor à ação.** O motor já manda "cobertura pelo INSS na data do acidente (calculado pelo
   sistema)", mas o prompt não diz o que fazer com cada valor. Com isso o modelo compara meses de cabeça.

A correção abaixo ataca a raiz em cada caso: um roteiro de decisão curto (A a E), regras de data com saída, uma
tabela da linha de cobertura e o texto exato de cada saída, com exemplo JSON.

---

## 1. Linha da data de hoje

**Problema.** Na 0317, o modelo usou o "Hoje é" como data do acidente:
- sc15[teve_clt] T10: "O acidente aconteceu em março de 2026 ... 32 meses";
- sc16[com_seguro] T9/T10: "03/2026 ... 36 meses";
- sc16[sem_seguro] T10: "em 2026".

O lead tinha escrito "até hj incha e doi".

ANTES:
```
A data de hoje vem no começo da conversa ("Hoje é ..."). Sempre considere esta data como a data atual E Faça as contas corretamente E Não precisa confirmar a data de HOJE, A DATA DE HOJE É A INFORMADA NO COMEÇO DA CONVERSA.
```
DEPOIS:
```
A data de hoje vem no começo da conversa ("Hoje é ..."). Sempre considere esta data como a data atual E Não precisa confirmar a data de HOJE, A DATA DE HOJE É A INFORMADA NO COMEÇO DA CONVERSA. A data de hoje **nunca** é a data do acidente nem a da saída do emprego ("até hoje dói", "até hj incha" fala da sequela, não da data). As contas de meses já vêm feitas nos FATOS DO SISTEMA: você não faz conta.
```
**Por quê.** O "Faça as contas corretamente" manda o modelo calcular, e no nosso motor quem calcula é o sistema.

## 2. CONTEXTO: a data do acidente sai da lista "já confirmados" e o que é do SDR não se pergunta de novo

**Problema.** 0317 sc15 e sc16, T6/T7: a IA nunca pergunta a data do acidente, porque o prompt diz que ela já foi
confirmada. Isso é a P1. No cenário de catálogo 03[extrator_sozinho] T4, a IA perguntou a sequela de novo.

ANTES:
```
- Sequela
- Mês e ano do acidente
- Exclusão de aposentado, RPPS e advogado constituído. ...
```
DEPOIS:
```
- Sequela
- Exclusão de aposentado, RPPS e advogado constituído. ...

Esses assuntos são do atendimento anterior: **nunca pergunte de novo** como foi o acidente, a sequela, o auxílio-doença, se era MEI/autônomo, se é aposentado ou se tem advogado. Se algum deles não apareceu na conversa, siga sem perguntar.
```

## 3. OBJETIVO: terceira saída e tabela de passagem

**Problema.** 0426 sem_seguro: no T11 a IA disse o resultado sem `transferir_para`, e a troca só saiu no T12. 0317
sc15[nunca_clt] T8: a IA explicou e desqualificou com um texto inventado.

ANTES:
```
- Calcular o prazo de forma precisa, sem inferências
- Decidir entre:
  - acione a Tool `closer`
  - acione a Tool `desqualificado`
```
DEPOIS (resumo; texto completo em "### COMO PASSAR O LEAD ADIANTE NESTE ATENDIMENTO"):
```
- Usar a conta pronta dos FATOS DO SISTEMA, sem inferências e sem fazer conta
- Decidir entre: ... `closer` / ... `desqualificado` / ou, quando as datas ficarem incertas, "Análise da equipe"

| Qualificado | "closer" | A frase do resultado e as duas frases de "Após qualificação" |
| Desqualificado | "desqualificado" | Só a mensagem de "Após desqualificação" |
| Análise da equipe | "" (vazio), com "notificacao": "analise_humana" | Só a frase de "Análise da equipe" |
* A decisão e a passagem saem sempre juntas, na mesma resposta. ...
```
**Por quê.** Liga o "acione a Tool" do escritório ao campo do JSON. Os nomes `closer` e `desqualificado` continuam no
texto, e `ferramentas_do_prompt` não abre destino novo (conferido).

## 4. PREMISSAS FIXAS (P2, P3 e P4 da sugerida, completadas)

**Problema.**
- 0317 sc15[nunca_clt] T5 a T8: a IA perguntou a CLT 3 vezes depois de "nunca".
- 0317 sc14 T9 a T11: a IA cobrou a demissão de quem era registrado.
- 0426 com_seguro T9: o modelo escreveu a conta inteira, por causa do "explicar o raciocínio".

ANTES:
```
- O mês/ano do acidente **já foi informado** anteriormente
- O lead em algum momento já trabalhou como CLT
- O lead **não estava CLT** na data do acidente
- Contribuição como autônomo **não mantém qualidade**
- Sempre explicar o raciocínio **de forma simples**
```
DEPOIS:
```
- O mês/ano do acidente em geral já foi informado antes. Confira na conversa e nos DADOS JÁ INFORMADOS. Se ele faltar para a conta, pergunte (pergunta 1.1). Sem a data do acidente, **NÃO calcule** e nunca a invente.
- Em geral o lead já trabalhou como CLT. Mas, se ele disser (agora ou antes na conversa) que **NUNCA** teve carteira assinada antes do acidente, vale a resposta dele: não pergunte de novo, não peça confirmação e siga "Após desqualificação".
- Em geral o lead **não estava CLT** na data do acidente. Mas, se ele disser que estava de carteira assinada no dia do acidente ("nunca saí de lá", "trabalho lá até hoje", "continuo registrado", registrado desde antes do acidente), vale a resposta dele: siga "Após qualificação" sem perguntar de demissão.
- Contribuição como autônomo **não mantém qualidade**
- Sempre explicar o raciocínio **de forma simples**: uma frase pronta de "Após qualificação", sem números, sem conta e sem passo a passo.
```
**Por quê.**
- "Fixas" pesam mais que a fala do lead: cada uma ganhou a saída do caso que a contradiz.
- O raciocínio continua sendo explicado, mas por uma frase pronta. Sem número na frase, não há como inventar número.

## 5. INÍCIO DO FLUXO: reler a conversa e "QUAL RESPOSTA MANDAR AGORA" (A a E)

**Problema.** O "ORDEM FIXA" faz o modelo recomeçar a lista:
- 0317 sc14 T8 e sc15[nunca_clt] T5: reenviou a frase de troca;
- 0317 sc16 T6 e 0426 sc16 T7: pediu a última CLT e a data juntas, sendo que o lead já tinha dito ao SDR "tinha saido
  da transportadora";
- 0317 sc16 T7: o lead respondeu "como eu falei";
- a frase "Agora vou confirmar..." era respondida com "sei nao" ou "pode sim" e o modelo não sabia o que fazer.

ANTES: (não havia; só o parágrafo "Nesse caso, irá realizar as perguntas...")

DEPOIS (resumo; texto completo na seção):
```
**ANTES DE CADA RESPOSTA, RELEIA A CONVERSA INTEIRA** ... "uns 8 meses", "faz uns 2 anos", "tinha saído da padaria", "nunca trabalhei de carteira" e "não sei" **já são respostas**: use-as.

## QUAL RESPOSTA MANDAR AGORA (confira nesta ordem, toda vez, e pare no primeiro item que valer)
A. nunca teve carteira → "Após desqualificação", nesta resposta.
B. aposentado → "Após desqualificação", nesta resposta.
C. de carteira assinada no dia do acidente → "Após qualificação", nesta resposta. (registrado desde [ano] sem o ano do acidente → pergunta 1.1; mesmo ano → 1 pergunta)
D. há a linha "cobertura pelo INSS na data do acidente (calculado pelo sistema)" → "DECISÃO PELOS FATOS DO SISTEMA".
E. senão → a primeira pergunta da lista cuja resposta ainda não está na conversa, e só ela.
Antes de enviar, confira: no máximo um "?", nenhuma pergunta já respondida, nenhuma conta anunciada.
```
**Por quê.** O gpt-4.1-mini segue melhor uma lista curta de checagem do que regras espalhadas. É o mesmo formato do
"QUAL RESPOSTA MANDAR AGORA" do `desqualificado.md`. Os exemplos novos (padaria, metalúrgica, supermercado) não são
dados de cenário.

## 6. Pergunta 1: nunca reenviar

**Problema.** 0317 sc14 T8 e sc15[nunca_clt] T5: um turno perdido em cada. No sc15, o "nunca trabalhei de carteira"
ficou sem resposta.

ANTES:
```
1- Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?
* Você **não** pode chamar a tool `desqualificado` como resposta dessa pergunta
- Analise toda memoria para prosseguir.
```
DEPOIS:
```
1- Agora vou confirmar algumas informações importantes sobre seu vínculo com o INSS, tudo bem?
* Esta frase **já foi enviada** ao lead na passagem para esta etapa: **nunca a envie de novo**. A resposta do lead a ela ("sim", "pode", "pode sim") só libera a próxima pergunta que falta.
* Você **não** pode chamar a tool `desqualificado` como resposta dessa pergunta ("sim", "pode", "tudo bem" nunca desqualificam). Mas, se na mesma mensagem o lead disser que nunca teve carteira assinada, isso é a resposta da pergunta 2 (item A).
- Analise toda memoria para prosseguir.
```
**Por quê.** A frase é a `mensagem_troca` do papel. O motor já a envia na passagem: se o SDR esquecer, o
`_com_frase_de_troca` insere. Então ela sempre foi enviada. O texto da pergunta 1 continua idêntico.

## 7. Pergunta 2: sozinha, "já respondida" e exemplos reais (P5/P6 da sugerida)

**Problema.**
- 0426 com_seguro T7 e teve_clt T7: "Qual foi a última vez...? Por favor, informe o mês e o ano da sua demissão."
  (duas perguntas).
- 0426 sem_seguro T8: "Entendi que você trabalhou como ajudante na transportadora, certo? Agora, por favor, poderia me
  informar o mês e o ano...?" (eco + 2 "?").
- 0317 sc15[nunca_clt] T6 a T8: CLT perguntada 3 vezes.
- Os exemplos "Não precisa / Sim claro, pode" são de pergunta de sim/não.

ANTES:
```
- Se **Resposta positiva que confirme** → prossiga
- Se **Resposta negativa ** → acionar a tool `desqualificado`.
(Exemplos de respostas negativas: Não precsa, não tem necessidade,)
(Exemplos de respostas positivas: Sim claro, pode, quero sim, sim, Podemos.)
```
DEPOIS:
```
* Envie esta pergunta sozinha: não junte o pedido do mês e do ano da demissão. Nunca presuma que houve demissão antes de o lead responder.
* **Já respondida** se o lead disse, agora ou antes, onde ou quando trabalhou de carteira (...): não pergunte de novo, vá para a 3. Se ele já disse também quando saiu (...), pule a 3.

- Se o lead disser quando ou onde trabalhou de carteira → prossiga
- Se o lead disser, agora ou antes na conversa, que **NUNCA** teve carteira assinada antes do acidente (ou que só teve depois do acidente) → acionar a tool `desqualificado`, sem perguntar de novo e sem confirmar ("você nunca trabalhou de carteira, certo?" é proibido).
- Se o lead disser que estava registrado no dia do acidente → item C ("Após qualificação").
(Exemplos de respostas negativas: "nunca tive carteira", "de carteira nunca", "sempre trabalhei por conta".)
(Exemplos de respostas positivas: "trabalhei no supermercado até 2022", "fui registrado na metalúrgica", "saí da padaria em maio de 2021".)
```
**Por quê.**
- A sugerida (P6) mandava "acionar a Tool `closer`" para quem era registrado. Agora isso aponta para "Após
  qualificação", que tem a frase exata. Sem a frase e com "?" na resposta, o motor segura a troca por um turno
  (`_segurar_transferencia`).
- Os exemplos da sugerida ("loja até 2023", "transportadora") eram dados dos cenários sc15 e sc16, e foram trocados.

## 8. Pergunta 1.1 (data do acidente): depois da 3, só quando a conta precisa

**Problema.** 0317 sc15 e sc16: a data do acidente nunca foi perguntada. Isso é a P1/P5. Mas a P5 da sugerida dizia
"nunca aceitar apenas o ano", e o SDR pergunta só o ano. Do jeito que estava, o modelo cobraria o mês de todo lead.

ANTES (sugerida, P5):
```
1.1 - Só se o mês e o ano do acidente ainda não foram ditos pelo lead na conversa: "Em que mês e ano foi o acidente?" (mesmas regras da pergunta 3: nunca aceitar apenas o ano, nunca presumir.)
```
DEPOIS (entre a pergunta 3 e a 4):
```
1.1 - Em que mês e ano foi o acidente?
* Pergunte **só** se a conta precisa dela: o lead já disse quando saiu do emprego e você não acha o ano do acidente numa fala dele; ou os FATOS DO SISTEMA dizem "data do acidente ... não informada pelo lead" ou "data do acidente igual ao mês atual ... confirme com o lead"; ou o item C precisa dela. Se o lead disse quanto tempo antes do acidente saiu ("uns 8 meses antes"), a conta não precisa dela: não pergunte.
* Se o lead já disse o ano e não o mês, não pergunte o mês aqui (só se a DECISÃO mandar).
* Mesmas regras de data da pergunta 3, inclusive a saída para "não sei".
```
**Por quê.**
- As condições são as linhas que o motor já manda (`contexto.fatos_da_calculadora`).
- O mês só é pedido quando a calculadora diz "perto do limite (falta o mês do acidente)".
- Com tempo relativo, a conta sai sem a data do acidente ("cerca de 8 meses"), e perguntar seria uma pergunta à toa.

## 9. Pergunta 3: data aproximada, "nunca fui demitido" e saída para "não sei" (P7 da sugerida, refeita)

**Problema.** 0317 sc14 T9 a T11: a mesma frase 3 vezes para "sei nao", com um lead que nunca foi demitido. A P7 da
sugerida manteve o "Refazer a pergunta até obter mês e ano".

ANTES:
```
Regras:
- Nunca aceitar apenas o ano
- Refazer a pergunta até obter mês e ano
- Nunca presumir datas
- A data pode ser em qualquer formato enviado.
```
DEPOIS (resumo; texto completo na pergunta 3):
```
* Quando souber a empresa, use o nome dela, com as palavras do lead: "Em que mês e ano você saiu da padaria?".
- "Demissão" é qualquer saída do emprego (...). "Nunca fui demitido" quer dizer: ou ele continuava no emprego no dia do acidente (item C), ou saiu de outro jeito (...). Se não der para saber qual dos dois, pergunte uma vez: "Você ainda trabalhava lá quando o acidente aconteceu?".
- Nunca presumir datas: nunca complete um mês ou um ano que o lead não disse.
- A data pode ser em qualquer formato enviado. Aproximado vale (...). Tempo relativo também vale (...): é a resposta desta pergunta, não peça o mês e o ano de novo.
- Se o lead disser só o ano, peça o mês **uma única vez**: "Lembra mais ou menos o mês?". Se ele não lembrar, não pergunte mais: siga com o que ele disse.
- **SAÍDA PARA "NÃO SEI" (nunca faça a mesma pergunta mais de 2 vezes):** 1º "não sei" → uma aproximação, uma única vez (com a dica da Carteira de Trabalho Digital); aproximação dada → aceite; ainda não sabe → NÃO pergunte de novo, NÃO desqualifique → "Análise da equipe".
```
**Por quê.**
- A conta do motor aceita data aproximada e faixa de meses (`aa._intervalo_meses_entre_demissao_e_acidente`). Se o
  ano sozinho não decidir, a linha de cobertura diz "perto do limite" e a tabela trata.
- A pergunta passa a ser feita no máximo 2 vezes, nunca 4.

## 10. Pergunta 4 (seguro-desemprego): uma vez, sem confundir com auxílio-doença

**Problema.** 0426 sc16 T4: "nao recebi nao, tava sem emprego" respondia ao auxílio-doença. O risco é o modelo tomar
isso como resposta do seguro, e a regra "já disse na conversa" puxa para esse erro.

ANTES: (só a pergunta e os prazos)

DEPOIS (acrescentado):
```
* Pergunte **uma vez** só. Se o lead já disse na conversa se recebeu ou não, não pergunte.
* Auxílio-doença ("encostado pelo INSS", "afastado pelo INSS") **não** é seguro-desemprego: "não recebi" dito sobre auxílio-doença não responde esta pergunta.
* "Não sei", "não lembro" também é resposta: não pergunte de novo, decida pela tabela abaixo.
```

## 11. Decidir na mesma resposta (P8 da sugerida, refeita)

**Problema.**
- 0317 sc16[com_seguro] T9: "Agora vou calcular o período de graça..." e o turno acaba.
- 0317 sc16[sem_seguro] T9: "Vamos calcular...".
- 0426 sem_seguro T10: "Entendi que você foi demitido em ... e não recebeu seguro-desemprego, certo? / Vou calcular
  agora...".
- 0317 teve_clt T10: "Vamos calcular agora...", com a conta inventada.

ANTES (sugerida, P8):
```
Com a resposta do seguro-desemprego, use a conta pronta dos FATOS DO SISTEMA, mostre-a em 1 frase simples e decida NA MESMA resposta (siga "Após qualificação" ou "Após desqualificação"). Nunca diga "vou calcular" e pare. Se faltar a data do acidente ou da demissão, pergunte-a em vez de anunciar a conta.
```
DEPOIS:
```
**DECIDA NA MESMA RESPOSTA (REGRA ABSOLUTA):** os FATOS DO SISTEMA chegam com a conta já feita, contando com a mensagem nova do lead. Quando o lead responde a última pergunta que faltava, a sua resposta **é a decisão** ("Após qualificação", "Após desqualificação" ou "Análise da equipe").
* **PROIBIDO** escrever "vou calcular", "vamos calcular", "calculando", "vou verificar", "vamos analisar juntos", "aguarde", "um momento" e parar. ...
* Nunca recapitule as respostas do lead antes da decisão ("Você foi demitido em ... e recebeu seguro-desemprego, certo?" é proibido).
* Se faltar alguma data, pergunte por ela em vez de anunciar a conta.
```
**Por quê.**
- Saiu o "mostre a conta em 1 frase", que chamava números.
- As três frases de anúncio que apareceram nas rodadas ficaram proibidas pelo nome.
- A recapitulação em forma de pergunta (eco + "certo?") também ficou proibida pelo nome.

## 12. DECISÃO PELOS FATOS DO SISTEMA (nova)

**Problema.** O motor já entrega `cobertura pelo INSS na data do acidente (calculado pelo sistema)`, mas o prompt não
dizia o que fazer com ela. O modelo comparava os meses com 12/24 de cabeça e se enganava. No catálogo 03[com_seguro]
foram 16 meses com seguro, e mesmo assim a IA desqualificou.

DEPOIS (tabela completa no arquivo):
```
Primeiro: se o seguro-desemprego ainda **não** foi perguntado nem dito na conversa, a resposta é a pergunta 4 (só ela). Depois ...:
| "coberta na data do acidente" | "Após qualificação" |
| "não coberta pelas datas" | "Após desqualificação" |
| "depende de ter recebido seguro-desemprego (falta saber)" | SIM → qualificação; NÃO → desqualificação; não sabe → "Análise da equipe" |
| "perto do limite (falta o mês ...)" | pergunta o mês uma vez; não sabe → "Análise da equipe" |
| "perto do limite: peça análise humana" | "Análise da equipe" |
| Linha da cobertura ausente | item E; se o lead já disse as duas datas, ou que não sabe → "Análise da equipe" |
* "conflito nas datas (calculado pelo sistema)": pergunte uma vez a data da saída; depois decida; conflito continua → "Análise da equipe".
```
**Por quê.**
- Os textos da tabela são os de `contexto.cobertura_na_data_do_acidente` e `fatos_da_calculadora`, conferidos no
  código.
- O seguro continua obrigatório, como manda o escritório.
- A linha "ausente com as duas datas ditas" cobre a falha do extrator sem pedir a data de novo e sem fazer conta.
- A linha "meses desde o acidente até hoje" foi proibida pelo nome: é o número que o modelo confundia.

## 13. CÁLCULO, ALGORITMO, FÓRMULAS: mantidos, como referência

**Problema.** 0426 com_seguro T9: "Calculando os meses entre ... temos 20 meses. ... Como 20 meses é menor que 24
meses...". Foi o PASSO 2 e o PASSO 4 do algoritmo, escritos para o lead.

ANTES:
```
(Calculadora: as contas de meses entre datas vêm prontas em FATOS DO SISTEMA, calculadas pelo sistema; use-as e nunca faça a conta de cabeça.)
```
DEPOIS:
```
(Calculadora: ... nunca faça a conta de cabeça. As regras, o algoritmo, as fórmulas e os exemplos abaixo só explicam a conta que o sistema **já fez**: não os execute, não os escreva ao lead e não diga que vai calcular.)
```
O MÉTODO ganhou o item 4: "Se a saída do emprego foi no mês do acidente ou depois dele, o lead estava CLT na data →
DENTRO DO PRAZO". É o que o motor já faz ("nenhum: o acidente foi ANTES da saída").

O algoritmo, as fórmulas e as 10 linhas de exemplo continuam **idênticos**. O título dos exemplos ganhou "As datas são
de exemplo, nunca do lead".

## 14. QUALIFICADO / DESQUALIFICADO: "na prática" e as proibições

ANTES: as duas definições por fórmula e "Você **NUNCA** pode chamar essa tool caso o lead não tenha respondido a
pergunta 2 ...".

DEPOIS (acrescentado, mantendo o texto original):
```
Também está QUALIFICADO quem estava registrado (CLT) no dia do acidente. Na prática: FATOS DO SISTEMA "coberta na data do acidente" = QUALIFICADO.
... Na prática: FATOS DO SISTEMA "não coberta pelas datas" = DESQUALIFICADO.
* (pergunta 2) ... (vale a resposta dada em qualquer momento da conversa, inclusive no atendimento anterior: "nunca tive carteira" já é resposta e desqualifica sem perguntar de novo)
* Nunca desqualifique quando os FATOS DO SISTEMA disserem "coberta na data do acidente", nem por falta de data (falta de data → "Análise da equipe").
```
**Por quê.** Fica igual à trava `periodo_coberto` do motor, que pede refazer quando a IA desqualifica alguém coberto.
Assim o modelo não gasta uma tentativa.

Na aposentadoria entrou "(só se ele disser; nunca pergunte)": aposentadoria é do SDR.

## 15. BLOQUEIO DE INDUÇÃO: sem laço

**Problema.**
- 0317 sc14 T9 a T11: "Para eu confirmar corretamente, preciso do mês e do ano exatos..." 3 vezes.
- 0317 sc16 T6 e 0426 sc16 T7: o lead diz "acho que eu ainda tava no prazo do inss" junto com "pode sim".

ANTES:
```
- Apenas DATAS (mês/ano) são aceitas como base de cálculo
- Caso o lead tente concluir por conta própria:
  - A IA deve responder:
    **“Para eu confirmar corretamente, preciso do mês e do ano exatos.”**
- Sem data → **NÃO CALCULA**
- Sem cálculo → **NÃO QUALIFICA**
```
DEPOIS:
```
- Apenas DATAS (mês/ano, aproximadas ou em tempo relativo) são aceitas como base de cálculo
- Caso o lead tente concluir por conta própria: não concorde nem discorde, não comente a opinião dele e faça a próxima pergunta que falta. Se a pergunta que falta é a data da saída, pode usar, **uma vez na conversa**:
    **“Para eu confirmar corretamente, preciso do mês e do ano em que você saiu.”**
  Se o lead não souber a data, siga a saída para "não sei" da pergunta 3 (nunca repita a frase).
- Sem data → **NÃO CALCULA** (pergunte a data que falta; nunca anuncie a conta sem ela)
- A opinião do lead **NUNCA QUALIFICA**: só a linha de cobertura dos FATOS DO SISTEMA, o "registrado no dia do acidente" ou a "Análise da equipe"
```
**Por quê.**
- A regra do escritório continua: o lead nunca decide.
- Saiu "exatos", que brigava com "aproximado vale".
- A frase passa a ser dita uma vez só e tem saída.

## 16. Após qualificação: tudo na mesma resposta, frase do resultado pronta

**Problema.** 0426 com_seguro T9: "Perfeito, obrigado pelas informações. Vamos analisar juntos... Você foi demitido em
março de 2023 e recebeu seguro-desemprego, certo? ... Calculando os meses ... Maravilha! Nós podemos te ajudar no seu
caso. Posso te explicar como funciona o Auxílio-Acidente?". Teve eco, conta, 3 "?" e a frase colada no parágrafo. O
roteiro do escritório ("Se responder SIM → Tool `closer`" antes do áudio) não dizia em que resposta transferir.

ANTES:
```
# Após qualificação
Quando o lead atender aos requisitos:
Enviar:
> Maravilha! Nós podemos te ajudar no seu caso.
Depois:
> Posso te explicar como funciona o Auxílio-Acidente?
* Se responder **SIM** → Tool `closer`
Enviar **somente o link**, sem texto adicional: (áudio Como Funciona)
Depois enviar:
> Conseguiu entender certinho como funciona o benefício?
```
DEPOIS (resumo):
```
Quando o lead atender aos requisitos, **na MESMA resposta** da decisão: preencha "transferir_para": "closer" (acione a Tool `closer`) e envie, nesta ordem, cada uma no seu balão:
1. A frase do resultado (escolha uma, copie, sem números):
   * pelas datas: "Pelas datas que você me passou, quando o acidente aconteceu você ainda estava no período de graça, o prazo em que o INSS continua protegendo quem saiu do emprego."
   * registrado no dia do acidente: "Como você estava de carteira assinada quando o acidente aconteceu, o seu vínculo com o INSS estava ativo."
Enviar: > Maravilha! Nós podemos te ajudar no seu caso.
Depois: > Posso te explicar como funciona o Auxílio-Acidente?
* "Maravilha!..." vai sozinha no balão, copiada letra por letra (...)
* Nesta resposta, a única pergunta é "Posso te explicar como funciona o Auxílio-Acidente?". Nada depois dela.
* Se responder **SIM** → Tool `closer` (já acionada junto com a frase acima)
* Exemplo CERTO (JSON) e Exemplo ERRADO (o da 0426).
O áudio e a pergunta abaixo são da etapa seguinte, enviados depois do "sim" do lead: não os envie na resposta da passagem.
(link do áudio e "Conseguiu entender certinho..." mantidos)
```
**Por quê.**
- O "explicar o raciocínio de forma simples" do escritório agora é uma frase sem número e sem promessa. Passa na
  `trecho_de_promessa` (conferido).
- O "Conseguiu entender certinho...?" continua no texto, mas marcado como da etapa seguinte. O closer já o envia, e
  repetir aqui era um dos erros da lista.

## 17. Após desqualificação: só a mensagem longa, sem explicação

**Problema.**
- 0317 sc15[nunca_clt] T8: "Para que eu possa analisar seu caso corretamente, é necessário que você tenha trabalhado
  de carteira...". Foi uma explicação jurídica inventada.
- 0317 teve_clt T10 e sc16 T10: o motivo foi dito com a data de hoje.
- 0426 sem_seguro T11/T12: decisão sem `transferir_para`.

ANTES:
```
### Após desqualificação
* **SEMPRE** Acionar imediatamente a Tool `desqualificado`.
* Informar de forma educada que não é possível prosseguir no atendimento.
```
DEPOIS (resumo):
```
* **SEMPRE** Acionar imediatamente a Tool `desqualificado`: preencha "transferir_para": "desqualificado" **na mesma resposta** da decisão.
* Informar de forma educada que não é possível prosseguir no atendimento: envie **só** a mensagem abaixo, exatamente assim, **sem nada antes** (...; o motivo é explicado ao lead logo depois, na mensagem seguinte do atendimento):
`Analisei com atenção o que você nos contou e, neste momento, ... Conte conosco!`
* **Não faça pergunta** nessa resposta. Nunca diga que o lead "não tem direito" nem "perdeu o direito", e não use a frase "Agora vou confirmar algumas informações...".
* Exemplo CERTO (JSON) e 3 Exemplos ERRADOS das rodadas.
```
**Por quê.**
- É a mesma mensagem e a mesma regra do SDR corrigido ("APÓS DESQUALIFICAR", conferido: texto idêntico).
- Ela contém a `mensagem_troca` do desqualificado.
- O `desqualificado.md` corrigido parte de "a frase já foi enviada" e, no PASSO A, manda o resumo com o MOTIVO REAL
  da tabela dele. Por isso o motivo não é dito aqui, e assim não sai duas vezes nem com a data errada.
- Sem "?" na resposta, o motor não segura a troca.

## 18. Análise da equipe (nova)

**Problema.** Não existia saída para o lead que não sabe a data nem o seguro. O resultado era o laço do sc14 ou uma
desqualificação por falta de dado.

DEPOIS:
```
### Análise da equipe
Quando a data da saída do emprego, a do acidente ou o seguro-desemprego ficarem incertos e a conta não decidir (...): não desqualifique, não pergunte de novo, preencha "notificacao": "analise_humana", deixe "transferir_para" vazio e escreva só:
> Para não ter erro nas datas, vou pedir para a nossa equipe conferir o seu caso com atenção, e retornamos por aqui.
* Não cite prazo de retorno ("em breve", "hoje ainda", "alguns dias", "5 dias úteis") e não faça pergunta nessa resposta.
* Exemplo CERTO (JSON).
```
**Por quê.**
- `analise_humana` está no esquema deste papel (`notificacao: true`), e o motor pausa o lead e avisa a equipe
  ("Agente pediu: analise_humana").
- O FORMATO_NOTIFICACAO pede exatamente "escreva ao lead que a equipe vai analisar e retornar por aqui".
- A proibição de prazo cobre o "5 dias úteis" visto em outras etapas.

## 19. Endereço do escritório: retomar a condução

ANTES: terminava em "> Certo! Podemos prosseguir?".
DEPOIS (acrescentado): `* Na resposta seguinte, retome a pergunta pendente desta etapa (sem repetir o áudio nem o endereço).`

**Por quê.** O erro "responder dúvida sem retomar a condução" estava na lista. Os 2 links e o endereço não mudaram.

## 20. OBJEÇÕES: reconduzir para a pergunta pendente; OBJ 1 e OBJ 7 sem promessa

**Problema.** As objeções terminam numa pergunta de fechamento ("Quer seguir?"), e esta etapa ainda está qualificando.
Somada à pergunta pendente, daria 2 "?". O "Enviar dados do escritório" não dizia de onde tirar os dados.

DEPOIS (acrescentado ao QUANDO USAR):
```
Nesta etapa, "reconduzir" é voltar à pergunta pendente do roteiro: use o texto da objeção **sem a pergunta final dele** e termine a resposta com a pergunta pendente (uma pergunta por resposta). "Enviar dados do escritório" = os DADOS DO ESCRITÓRIO da base de conhecimento, antes da pergunta pendente. Cada objeção vai uma vez: se ela voltar, responda em 1 frase e retome a pergunta.
```
Duas frases trocadas, **iguais às mudanças 14 e 15 do closer** (mesmo agente, mesma regra de promessa):
- OBJ 1. ANTES: `O maior risco é continuar sem receber um direito seu.` DEPOIS: `O maior risco é deixar o tempo passar sem fazer o pedido.`
- OBJ 7. ANTES: `Quem inicia cedo recebe cedo.` DEPOIS: `Quem inicia cedo resolve mais cedo.`

As OBJ 1 a 11, os títulos, as marcações "Enviar / Não enviar dados do escritório" e o link do áudio da OBJ 11 não
mudaram. Se o escritório preferir as frases originais da OBJ 1 e da OBJ 7, basta desfazer estas duas trocas. Elas não
caem na trava de produção, mas afirmam que o lead tem direito ou vai receber.

## 21. REGRAS DE ATENDIMENTO: regras curtas onde faltava saída

ANTES: `* Faça somente uma pergunta por vez` e as demais regras do escritório.

DEPOIS (o original mantido, com estes acréscimos):
```
* Faça somente uma pergunta por vez (no máximo um "?" por resposta)
* Nunca pergunte o que o lead já respondeu: antes de perguntar, confira a conversa e os DADOS JÁ INFORMADOS
* Nunca repita a mesma pergunta mais de 2 vezes: use a saída para "não sei" da pergunta 3
* Nunca devolva como pergunta o que o lead acabou de dizer (...): acolha em poucas palavras ("Entendi.", "Certo.", "Obrigada por me contar.") e faça a próxima pergunta
* Fale como gente: frases curtas, use as palavras do lead (o nome da empresa, "saiu", "foi mandado embora"); nada de "Por favor, me informe" em toda mensagem
* Nunca dê opinião sobre o caso além do roteiro (nada de "não ter recebido auxílio-doença pode complicar" ou "isso ajuda no seu caso")
* Não peça documentos, laudos, exames nem foto da carteira de trabalho
* Se o lead fizer uma pergunta ou tiver uma dúvida, responda em 1 ou 2 frases pelo roteiro e, na mesma resposta, retome a pergunta pendente desta etapa. O que o roteiro e a base não respondem: diga que vai confirmar com a equipe, sem inventar
* Nunca prometa resultado: nunca use "garantir"/"garantia" ligado a benefício, direito ou resultado, nunca diga "você tem direito" nem "você vai receber", e nunca cite prazo do processo
```
**Problemas cobertos:**
- eco "certo?": 0426 sem_seguro T8 e T10; 0426 com_seguro T9;
- "Por favor, informe..." seguido: 0317 teve_clt T7 e T8;
- opinião jurídica inventada: 0317 sc17 T3, no SDR (vale como prevenção aqui);
- pedido de laudo: 0317 sc03 T13, no closer;
- "garantir": 7 ocorrências no closer nas três rodadas.

Cada regra corresponde a um item da lista de micro-alucinações. As regras do escritório ("Nunca revelar", "não
acumulativas", "Nunca dizer que recebe somente textos") continuam iguais.

## 22. SISTEMA DE NOTIFICAÇÃO

ANTES: o parágrafo dos avisos que o sistema percebe sozinho (mantido igual).
DEPOIS (acrescentado): `A única notificação que você preenche nesta etapa é "analise_humana", e só no caso de "Análise da equipe" acima.`

---

## Conferência por script

`conferir_periododegraca.py`, no scratchpad da sessão
(`C:/Users/joaov/AppData/Local/Temp/claude/3daca395681118a1/65175654-ced8-4918-a48b-f45988c6d47b/scratchpad/`), compara
`periododegraca.md` com `sousa_costa.json`, com o `sdr.md` corrigido e com o motor (`app.cerebro.catalogo` e
`app.cerebro.travas`). Resultado: **tudo certo**.

- **(a) Frases de troca.**
  - A frase do `closer` aparece idêntica (4x: o "Enviar:", a regra do balão, o exemplo certo e o exemplo errado).
  - A do `desqualificado` aparece idêntica, dentro da mensagem longa (2x). A mensagem longa é igual à do SDR corrigido.
  - A do próprio papel continua idêntica na pergunta 1 (1x, como no fiel).
  - A de `contratos` não aparece.
  - Os campos `papeis.*` do snapshot não foram tocados.
- **(b) Links.** Os 4 links do fiel estão presentes e nenhum link novo entrou: áudio Como Funciona, os 2 áudios de
  endereço e o áudio da OBJ 11.
- **(c) Promessas.**
  - "garant" só aparece na linha de proibição.
  - "você tem direito" e "você vai receber" só aparecem em linhas de proibição. "um direito seu" e "recebe cedo" não
    aparecem.
  - As 124 falas do roteiro (texto entre aspas, linhas ">" e OBJ) passam em `travas.trecho_de_promessa`.
- **(d) Motor.**
  - `catalogo.ferramentas_do_prompt` → `['desqualificado', 'closer']`, sem ações: não abre destino novo.
  - `montar_sistema` monta sem erro.
  - `analise_humana` está no esquema.
  - Os 3 exemplos JSON são válidos no esquema do papel (`mensagens`, `transferir_para`, `ferramenta`, `notificacao`),
    têm no máximo um "?" e passam na trava.
  - Os exemplos com troca passam em `catalogo.tem_frase` com a `mensagem_troca` do destino, então o motor não segura a
    troca nem insere a frase de novo.
- **(e) Estrutura.**
  - Os 38 títulos do fiel estão presentes, na mesma ordem.
  - Títulos novos: "COMO PASSAR O LEAD ADIANTE", "QUAL RESPOSTA MANDAR AGORA", "DECISÃO PELOS FATOS DO SISTEMA" e
    "Análise da equipe".
  - As OBJ 1 a 11 estão presentes. O endereço (R. Rebelo Horta, 104) está igual.
- **(f) Sem dados de cenário.** Não aparecem "transportadora", "loja de roupa", "março de 2023", "julho de 2023",
  "novembro de 2024" nem "2026". Exemplo com a data do cenário vira data inventada quando o lead não diz a dele.

**Não testado com o modelo.** Esta tarefa não pôde chamar a API. O efeito real só aparece rodando de novo a bateria
`cenarios_sousa_costa` com este texto no `instrucao` do período de graça. Os cenários que passam por esta etapa são o
sc16 (com_seguro e sem_seguro), o sc15 (teve_clt_ha_meses e nunca_clt, este só se o SDR transferir) e o sc14. Na 0523,
o sc16 ficou de fora por causa do teto de custo, então vale rodá-lo primeiro.


## Corretor, rodada 1 (2026-11-25)

Mudanças mínimas pedidas pela revisão. Frases de troca (mensagem_troca), links de mídia e dados do escritório intactos.

- **[1] Conciliação com o FORMATO do motor.** Confirmado.
  - Nova regra depois de "Nunca recapitule": a citação "Você comentou que..." vale só quando a IA pula uma pergunta, e deve ser curta, sem datas, números nem nome de empresa.
  - Na resposta da decisão (closer, desqualificado ou "Análise da equipe") não se cita nada: a resposta é só o texto pronto da decisão.
- **[7]/[15] A palavra "demissão" voltou aos pedidos de data.** Confirmado.
  - O cartão do sc16 só responde à data quando a pergunta casa com /demiss|mandad[oa] embora/, e o "perguntar_antes" exige /demiss/.
  - Com "você saiu", o sc16 caía em "Análise da equipe".
  - Pergunta 3 com o nome da empresa.
    - ANTES: "Em que mês e ano você saiu da padaria?".
    - DEPOIS: "Em que mês e ano foi a sua demissão (a saída) da padaria?". A regra também diz para não tirar a palavra "demissão".
  - Aproximação do "não sei".
    - ANTES: "mais ou menos em que mês e ano você saiu?".
    - DEPOIS: "mais ou menos em que mês e ano foi a sua demissão?".
  - BLOQUEIO DE INDUÇÃO.
    - ANTES: "preciso do mês e do ano em que você saiu."
    - DEPOIS: "preciso do mês e do ano da sua demissão."
  - Conflito nas datas (mesmo problema, fora da lista da revisão).
    - ANTES: "em que mês e ano você saiu da [empresa]?".
    - DEPOIS: "em que mês e ano foi a sua demissão (a saída) da [empresa]?".
- **[17] Não aplicado** (ver MUDANCAS_sdr.md, item [6]). A OBJ 1 e a OBJ 7 ficam com o texto novo, e o SDR e o Contratos passaram a usá-lo também.
