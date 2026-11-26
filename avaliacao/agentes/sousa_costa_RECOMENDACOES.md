# Recomendações de prompt ao Sousa e Costa (`sousa_costa_sugerido.json`)

Origem: rodada real de 2026-11-25 (`avaliacao/resultados/2026-11-25_0317_agente-sousa-costa`), achados verificados da
área "prompt". O snapshot fiel **não mudou**: `sousa_costa.json` continua sendo a cópia do n8n, e a bateria continua
medindo o prompt real. `sousa_costa_sugerido.json` é o fiel com **só** as mudanças de texto abaixo, além de `agente.id`
(`agente-sousa-costa-sugerido`, para o relatório sair em outra pasta) e `origem`.

Cada mudança tem um código (S = SDR, P = Período de Graça, C = Closer, K = Contratos, A = Assinatura, D = Desqualificado).
O **ANTES** é o trecho literal do prompt (para achar com Ctrl+F no n8n ou no painel) e o **DEPOIS** é o texto para colar no
lugar. As trocas foram feitas por script, conferindo quantas vezes cada trecho aparece (o Closer repete o prompt inteiro
duas vezes: C1, C2 e C3 valem para **as duas cópias**).

Para medir: `python -m app.avaliacao comparar --agente-a avaliacao/agentes/sousa_costa.json --agente-b
avaliacao/agentes/sousa_costa_sugerido.json --cenarios avaliacao/cenarios_sousa_costa --teto-usd <teto>` (modo real, pago:
quem roda é o usuário).

## Achado → mudança

| achado | caso / turno | etapa | mudanças |
|---|---|---|---|
| 0 | sc02 T22 e T27: 3 "?" na confirmação | contratos | K1, K2 |
| 1 | sc03 T13–T15: pede o nome dentro do closer e transfere sem a frase | closer | C1 |
| 2 | sc03 T21: pede o número que o lead já mandou ("418") | contratos | K6, K7, K8 |
| 3 | sc03 T27: 3 "?" na confirmação | contratos | K1, K2 (o mesmo do 0) |
| 4 | sc10 T15–T16: pede o CPF de novo por "formato incorreto" | contratos | K3, K4, K5 |
| 5 | sc10 e sc11 T2: pula a pergunta do ano | sdr | S1, S3, S8 |
| 6 | sc14 T4–T7: repete a pergunta da CLT e usa a 5.1 com quem é CLT | sdr | S3, S4, S5, S11 |
| 7 | sc19 T2–T4 (e sc18, sc14): pula a pergunta do ano | sdr | S1, S3, S8 |
| 8 | sc14 T9–T11: laço "mês e ano exatos da sua demissão" | periododegraca | P4, P5, P6, P7 |
| 9 | sc14 T7: a 5.1 literal tem 2 "?" | sdr | S6 |
| 10 | sc19 T10: OBJ 4 sem os dados do escritório | closer | C2, C3 |
| 11 | sc15 e sc16 (4 casos) T2 e T6/T7: ninguém pergunta a data do acidente | sdr e periododegraca | S1, S8, P1, P2, P5 |
| 12 | sc15[nunca_clt] T5–T7: pergunta a CLT 3 vezes depois de "nunca" | periododegraca | P3, P6 |
| 13 | sc16 (2 casos) T9: "Agora vou calcular..." e para | periododegraca | P8 |
| 14 | sc17, sc12, sc15, sc13: pula o ano (1 de 22 conversas perguntou) | sdr | S1, S3, S8 |
| 15 | sc15[mais_de_3_anos] T7 e sc17[sem_documentos] T6: o motivo dito não é o real | desqualificado | D1, D2 |
| 16 | sc17[com_documentos] T3: "não ter recebido auxílio-doença pode complicar" | sdr | S2 |
| conflito conhecido | FAQ da Assinatura manda imprimir (sc02, reprovação esperada) | assinatura | A1 |
| conflito conhecido | 5.1 (">3 anos → desqualificado") contra TRAVAS ("Teve CLT antes → período de graça") | sdr | S7, S9, S10 |

---

## SDR

### S1. Pergunta 2 tem o corpo copiado da pergunta 1 (achados 5, 7, 11, 14)

Problema: o título da pergunta 2 é "Em qual ano aconteceu o acidente?", mas a linha embaixo dela é cópia da linha da
pergunta 1 ("acolha com empatia e depois continue"). O modelo lê como "passe para a 3". Na rodada só 1 das 22 conversas
perguntou o ano (sc13[aposentada_por_invalidez] T2). sc10, sc11, sc14, sc15, sc16, sc17, sc18, sc19 e sc12[so_no_passado]
pularam. O Período de Graça parte do princípio de que o mês e o ano do acidente já foram ditos, e o SDR pede prova rural
"da época do acidente", então a data importa.

ANTES:
```
### 2. Em qual ano aconteceu o acidente?

Quando o lead contar sobre o acidente, acolha com empatia brevemente e depois continue.
```
DEPOIS:
```
### 2. Em que mês e ano aconteceu o acidente?

Pergunte SEMPRE, logo depois do relato e antes da pergunta 3, mesmo que o lead seja CLT. Só pule se o lead já disse o mês/ano com as próprias palavras ("até hoje dói" não é data). Se não lembrar o mês, aceite só o ano; se não lembrar o ano, pergunte "mais ou menos em que ano?" e aceite o aproximado. Incerteza de data em acidente antigo segue os "Casos especiais" do período de graça.
```
A pergunta 1 fica como está: a linha dela está certa para ela.

### S2. Pergunta 3 não diz o que fazer no NÃO (achado 16)

Problema: sc17[com_documentos] T3, "Ele não ter recebido auxílio-doença pode complicar, mas vamos ver o que dá pra
fazer." É uma opinião jurídica inventada e desanimadora: o auxílio-doença prévio não é requisito, e as REGRAS PARA
QUALIFICAR não o exigem. A pergunta 3 só trata o SIM, e o modelo preencheu a lacuna.

ANTES:
```
* Se **SIM** → perguntar por quanto tempo
```
DEPOIS:
```
* Se **SIM** → perguntar por quanto tempo
* Se **NÃO** → não comente nem avalie (não ter recebido auxílio-doença não impede o pedido); siga para a pergunta 4.
```

### S3. Pergunta 4: "registrado desde [ano anterior]" é CLT na data, e o ano vem antes (achados 5, 6, 7, 14)

Problema: sc14 T3, o lead diz "sou registrado no mercado desde 2021". T4 e T6 repetem a pergunta da CLT, e T7 vai para o
período de graça. Os exemplos "Sou fichado → periododegraca" puxam contra o "CLT SIM → closer". E o "Se SIM → closer" não
pede o ano, que fica parecendo dispensável.

ANTES:
```
* Se **SIM** → acionar Tool `closer`
* Se **NÃO** → **NÃO acionar nenhuma Tool neste momento**. ...
```
DEPOIS (a linha do NÃO continua igual):
```
* Se **SIM** (e o ano do acidente já foi perguntado na pergunta 2) → acionar Tool `closer`
* Se o lead disser que é/está registrado (fichado) desde um ano ANTERIOR ao do acidente, ou que continua no mesmo emprego até hoje, a resposta é SIM (CLT na data) → acionar Tool `closer`. Não repita a pergunta 4.
* Se **NÃO** → **NÃO acionar nenhuma Tool neste momento**. ...
```

### S4. Exemplos "Sou fichado / Já fui CLT → periododegraca" sem limite (achado 6)

ANTES:
```
Exemplos importantes (Possibilidades que podem indicar necessitar do calculo periodo de graça):
```
DEPOIS:
```
Exemplos importantes (Possibilidades que podem indicar necessitar do calculo periodo de graça; valem só quando o lead NÃO diz desde quando está registrado ou diz que saiu do emprego — "sou fichado desde [ano anterior ao acidente]" é CLT na data → Tool `closer`):
```

### S5. A pergunta 5.1 é só do MEI/autônomo (achado 6)

Problema: sc14 T7, a IA mandou o texto da 5.1 ("há quanto tempo havia saído da última empresa?") a um lead CLT.

ANTES:
```
Quando o lead responder **SIM** na pergunta 5 (era MEI, Autônomo ou Contribuinte Individual), enviar:
```
DEPOIS:
```
Quando o lead responder **SIM** na pergunta 5 (era MEI, Autônomo ou Contribuinte Individual), enviar (esta mensagem é só para esse caso; nunca use com quem disse que está ou estava registrado):
```

### S6. A 5.1 tem duas perguntas numa mensagem (achado 9)

Problema: sc14 T7, 2 "?" numa mensagem, contra "Faça somente uma pergunta por vez". A trava de produção também barraria
(trava_sombra `muitas_perguntas` no sc14).

ANTES:
```
> Quando você sofreu o acidente, há quanto tempo havia saído da última empresa? Eram meses ou já eram anos? Dependendo do tempo, ...
```
DEPOIS (o resto da frase continua igual):
```
> Quando sofreu o acidente, fazia meses ou anos que tinha saído da última empresa? Dependendo do tempo, ...
```
Os cartões do sc15 ("última empresa" / "meses ou anos") continuam reconhecendo a pergunta. A descrição do sc15 ("até 2
perguntas por turno: a mensagem literal da 5.1 tem duas") deixa de valer para o sugerido.

### S7, S9, S10. Conflito conhecido: 5.1 (">3 anos → desqualificado") contra TRAVAS ("Teve CLT antes → período de graça")

Problema (já registrado na descrição do sc15[saiu_ha_mais_de_3_anos]): a 5.1 manda desqualificar quem saiu da empresa
mais de 3 anos antes do acidente, e as TRAVAS e o "Sobre MEI" mandam todo mundo que teve CLT antes para o período de
graça. Os "Casos especiais" ainda proíbem desqualificar com incerteza de tempo. Pelas regras do próprio escritório
(período de graça de até 24 meses), quem saiu há mais de 3 anos está fora de qualquer jeito. A sugestão deixa a 5.1
mandar quando o lead é claro, e o período de graça mandar quando há dúvida.

S7 — ANTES:
```
* Se o cliente foi demitido **a mais de 3 anos antes do acidente** → Acionar Tool `desqualificado`
```
S7 — DEPOIS:
```
* Se o cliente disser com clareza que saiu da última empresa **há mais de 3 anos antes do acidente** → Acionar Tool `desqualificado` (esta regra vale mesmo com o "Teve CLT antes → período de graça" das TRAVAS; se houver dúvida sobre o tempo, acionar Tool `periododegraca`)
```
S9 (TRAVAS ABSOLUTAS) — ANTES:
```
Teve CLT antes → período de graça.**
```
S9 — DEPOIS:
```
Teve CLT antes → período de graça (exceto pela regra da 5.1: saiu da última empresa há mais de 3 anos antes do acidente → DESQUALIFICADO).**
```
S10 ("Sobre MEI/Autônomo") — ANTES:
```
Se teve CLT antes → caminho Período de Graça.
```
S10 — DEPOIS:
```
Se teve CLT antes → caminho Período de Graça (salvo a regra dos mais de 3 anos da 5.1).
```

### S8. "Sofreu acidente (em qualquer ano)" (achados 5, 7, 11, 14)

ANTES:
```
* Sofreu acidente (em qualquer ano)
```
DEPOIS:
```
* Sofreu acidente (o ano não desqualifica, mas precisa ser perguntado: pergunta 2)
```

### S11. "Casos especiais da Tool periododegraca" sem limite (achado 6)

ANTES:
```
### Casos especiais da Tool `periododegraca`

```
DEPOIS (a lista que vem depois continua igual):
```
### Casos especiais da Tool `periododegraca`

Estes casos valem quando o lead não sabe a data do vínculo ou diz que saiu do emprego. Quem diz que está registrado desde antes do acidente (ou no mesmo emprego até hoje) é CLT na data → Tool `closer`.

```

---

## PERÍODO DE GRAÇA

### P1, P2. Presume que a data do acidente já foi dita (achado 11)

Problema: sc15 e sc16, T6/T7. A IA vai direto para "Qual foi a última vez que trabalhou de carteira..." e nunca pergunta
a data do acidente, porque o prompt diz que ela já foi confirmada. Como o SDR pulava a pergunta (S1), a conta ficava sem
base, ou caía na data de hoje.

P1 — ANTES (lista "já passou pelas etapas iniciais... com confirmação de:"):
```
- Sequela
- Mês e ano do acidente
```
P1 — DEPOIS:
```
- Sequela
```
P2 — ANTES (PREMISSAS FIXAS):
```
- O mês/ano do acidente **já foi informado** anteriormente
```
P2 — DEPOIS:
```
- O mês/ano do acidente em geral já foi informado antes. Se o lead não disse o mês e o ano do acidente na conversa, pergunte (pergunta 1.1). Nunca use a data de hoje como data do acidente; sem ela, NÃO calcule.
```

### P3. Premissa "o lead em algum momento já trabalhou como CLT" (achado 12)

Problema: sc15[nunca_clt] T5–T7. O lead diz "nunca trabalhei de carteira", e a IA pergunta de novo duas vezes, porque a
premissa diz que ele já trabalhou.

ANTES:
```
- O lead em algum momento já trabalhou como CLT
```
DEPOIS:
```
- Em geral o lead já trabalhou como CLT; se ele disser que nunca teve carteira assinada, vale a resposta dele
```

### P4. Premissa "o lead não estava CLT" sem saída (achado 8)

ANTES:
```
- O lead **não estava CLT** na data do acidente
```
DEPOIS:
```
- O lead **não estava CLT** na data do acidente (se ele disser que nunca saiu do emprego ou que estava registrado na data do acidente, vale a resposta dele: acione a Tool `closer`)
```

### P5. Pergunta da data do acidente e "não presuma demissão" (achados 8 e 11)

Problema: sc14 T9, a IA pulou a pergunta 2 e foi direto ao "mês e o ano exatos da sua demissão" com um lead que nunca
foi demitido.

ANTES:
```
2 - Qual foi a última vez que trabalhou de carteira assinada ( CLT ) antes do acidente ?
```
DEPOIS:
```
1.1 - Só se o mês e o ano do acidente ainda não foram ditos pelo lead na conversa: "Em que mês e ano foi o acidente?" (mesmas regras da pergunta 3: nunca aceitar apenas o ano, nunca presumir.)

2 - Qual foi a última vez que trabalhou de carteira assinada ( CLT ) antes do acidente ?
* Faça esta pergunta antes de falar em demissão: nunca presuma que houve demissão.
```

### P6. Exemplos da pergunta 2 copiados de uma pergunta de sim/não (achados 8 e 12)

Problema: "Não precisa / Sim claro, pode" não respondem a "qual foi a última vez". Não havia saída para "nunca tive
carteira" (sc15[nunca_clt]) nem para "nunca saí do emprego" (sc14).

ANTES:
```
- Se **Resposta positiva que confirme** → prossiga
- Se **Resposta negativa ** → acionar a tool `desqualificado`.
(Exemplos de respostas negativas: Não precsa, não tem necessidade,)
(Exemplos de respostas positivas: Sim claro, pode, quero sim, sim, Podemos.)
```
DEPOIS:
```
- Se o lead disser quando ou onde trabalhou de carteira → prossiga
- Se o lead disser, agora ou antes na conversa, que NUNCA teve carteira assinada → acionar a tool `desqualificado`, sem perguntar de novo.
- Se o lead disser que nunca saiu do emprego ou que estava registrado na data do acidente → acionar a Tool `closer` (é CLT na data).
(Exemplos de respostas positivas: "trabalhei na loja até 2023", "fui registrado na transportadora".)
(Exemplos de respostas negativas: "nunca tive carteira", "sempre trabalhei por conta".)
```
A regra da pergunta 1 ("não pode chamar a tool `desqualificado` como resposta dessa pergunta") fica como está.

### P7. "Refazer a pergunta até obter mês e ano" sem saída para "não sei" (achado 8)

Problema: sc14 T10 e T11, a mesma frase repetida depois de "sei nao". Um lead real que não lembra a data cai no mesmo laço.

ANTES:
```
- Refazer a pergunta até obter mês e ano
```
DEPOIS:
```
- Refazer a pergunta até obter mês e ano
- Se o lead disser 2 vezes que não sabe/não lembra, peça uma aproximação ("mais ou menos em que mês e ano?"); se ainda assim não souber, preencha a notificação `analise_humana` (uma pessoa da equipe assume).
```

### P8. Anuncia a conta e para (achado 13)

Problema: sc16[com_seguro] e sc16[sem_seguro] T9, "Agora vou calcular o período de graça..." e o turno acaba sem resultado
nem pergunta. A decisão só sai no T10, depois de uma fala vazia do lead.

ANTES:
```
- Se **NÃO** → prazo máximo: **12 meses de qualidade de segurado**
```
DEPOIS:
```
- Se **NÃO** → prazo máximo: **12 meses de qualidade de segurado**

Com a resposta do seguro-desemprego, use a conta pronta dos FATOS DO SISTEMA, mostre-a em 1 frase simples e decida NA MESMA resposta (siga "Após qualificação" ou "Após desqualificação"). Nunca diga "vou calcular" e pare. Se faltar a data do acidente ou da demissão, pergunte-a em vez de anunciar a conta.
```
No n8n, troque "use a conta pronta dos FATOS DO SISTEMA" por "use a tool Calculator".

---

## CLOSER (as mudanças valem para as DUAS cópias do prompt)

### C1. ETAPA 5: "Acionar a Tool contratos" duas vezes (achado 1)

Problema: sc03. No T13 a lead diz "vamos fazer sim, o que vc precisa dele?", e a IA, ainda no closer, inventa "Preciso dos
documentos pessoais dele e comprovantes médicos ou laudos". No T14, "pode sim", e a IA pede "o nome completo do seu
marido" sem transferir (`dado_fora_de_hora`). No T15 transfere sem a frase exata (`transferencia_sem_frase`). O prompt
manda acionar `contratos` no "sim" e de novo quando chega o nome. No n8n a 2ª chamada não fazia mal, mas aqui a 1ª já
tira o lead do closer, e o modelo juntou as duas: pediu o nome no closer e só transferiu quando o nome chegou.

ANTES (as duas cópias):
```
Quando o lead responder **sim**:


### 👉 Acionar a Tool `contratos`.


Mensagem seguinte:


**“Excelente! Por gentileza, me informe seu nome completo para darmos continuidade à formalização.”**


Quando o lead enviar o nome completo:


### 👉 Acionar novamente a Tool `contratos`.
```
DEPOIS:
```
Quando o lead responder **sim** (mesmo com uma pergunta junto, como "o que você precisa?"):


### 👉 Na MESMA resposta, acione a Tool `contratos` e envie exatamente:


**“Excelente! Por gentileza, me informe seu nome completo para darmos continuidade à formalização.”**


⚠ Não peça o nome (nem nenhum outro dado) sem acionar a Tool `contratos`: quem coleta os dados é o Contratos.  
⚠ Nunca peça documentos, laudos ou comprovantes.
```
No n8n, troque "Tool `contratos`" pelo nome da tool de lá (`contrato`).

### C2. "→ Enviar dados do escritório." depois de um texto entre aspas (achado 10)

Problema: sc19 T10, a lead diz que outro advogado "faz mais barato", e a IA manda a OBJ 4 literal, sem OAB, CNPJ nem
Instagram. A instrução vem depois de um texto citado, e o modelo reproduz só o texto. A seção "# DADOS DO ESCRITÓRIO"
existe, mas nada liga uma à outra.

ANTES (OBJ 1, 2, 4 e 9, nas duas cópias: 8 vezes):
```
→ **Enviar dados do escritório.**
```
DEPOIS:
```
→ **Na mesma resposta, num balão separado, envie os dados do escritório:** Sousa e Costa Advogados — CNPJ 44.326.345/0001-05 — Dr. Eduardo Costa Oliveira (OAB/MG 150.650) e Dr. Pierre Luiz de Sousa (OAB/MG 201.389) — Instagram: https://www.instagram.com/sousaecostaadvogados?igsh=MWgxdWxxdGdzMWV6cQ==
```
"→ **Não enviar dados do escritório.**" (OBJ 3, 5, 6, 7, 8 e 10) fica como está.

### C3. Regra 6 da ETAPA 6 contra a OBJ 4 (achado 10)

Problema: a regra 6 só deixa mandar os dados "quando a objeção envolver confiança". Preço (OBJ 4) não parece confiança, e
a regra puxa contra o "Enviar dados" da própria OBJ 4.

ANTES (as duas cópias):
```
6) **Enviar dados do escritório apenas quando a objeção envolver confiança**
```
DEPOIS:
```
6) **Enviar os dados do escritório sempre que a objeção indicar (OBJ 1, 2, 4 e 9), na mesma resposta**
```
A mesma dupla (OBJ com "→ Enviar dados do escritório." e regra 6) aparece no **Contratos**, e as OBJ também aparecem no
SDR e no Período de Graça. Só o Closer teve falha medida, por isso o sugerido só mexe nele. Se o escritório quiser manter
tudo igual, a mesma troca vale nos outros prompts.

---

## CONTRATOS

### K1, K2. A confirmação final tem 3 "?" (achados 0 e 3)

Problema: sc02 T22 e T27, e sc03 T27. "...tudo bem?" + resumo + "Está tudo correto? Posso gerar o contrato?" dão 3
perguntas numa resposta, contra o "Perguntar 1 campo por vez" do próprio prompt. A IA seguiu o roteiro. A checagem
continua contando: a correção é no prompt.

K1 — ANTES:
```
> Vamos confirmar juntos todos os seus dados para garantir que está tudo certinho, tudo bem?
```
K1 — DEPOIS:
```
> Vamos confirmar juntos todos os seus dados para garantir que está tudo certinho.
```
K2 — ANTES:
```
> Está tudo correto? Posso gerar o contrato?
```
K2 — DEPOIS:
```
> Confere se está tudo certo para eu gerar o contrato?
```

### K3, K4, K5. CPF fora da tolerância de formato (achado 4, reforço secundário)

Problema: sc10 T15–T16 e seguintes, "O CPF que você enviou está com um formato incorreto" e "o último grupo deve ter dois
dígitos": a IA comparou "205.096.961.98" com o exemplo "123.456.789-00" das regras do zapsign. O prompt já dizia "Nunca
bloquear por falta de pontuação" e "Nunca solicitar reenvio", e o modelo desobedeceu. A causa principal é o modelo e o
motor, e estas trocas só tiram a ambiguidade.

K3 — ANTES (Tolerância Total de Formatação):
```
* CEP
* Telefone
  Nunca pedir reenvio. Correção sempre **interna**.
```
K3 — DEPOIS:
```
* CEP
* Telefone
* CPF (com ou sem pontos, traço ou espaços; ponto no lugar do traço também vale)
* RG
  Nunca pedir reenvio. Correção sempre **interna**.
```
K4 — ANTES (No caso do CPF):
```
* Se o sistema avisar que o CPF está errado, peça novamente explicando o motivo do erro
```
K4 — DEPOIS (o resto da linha, "(nessa mensagem a regra de Máximo de caracteres...)", continua igual):
```
* Só peça o CPF de novo quando o sistema avisar que ele é inválido (dígitos verificadores). Nunca peça de novo por causa de pontuação, formato ou quantidade de dígitos de cada grupo.
* Se o sistema avisar que o CPF está errado, peça novamente explicando o motivo do erro
```
K5 — ANTES (Regras da ferramenta zapsign; no n8n, na descrição da tool `criardocumento`):
```
* CPF com pontuação (ex.: 123.456.789-00) e RG com pontuação (ex.: 12.345.678-9); o RG é opcional.
```
K5 — DEPOIS:
```
* CPF e RG vão para o contrato com pontuação (ex.: 123.456.789-00 e 12.345.678-9): é o formato interno do contrato, que o sistema aplica sozinho. Nunca exija esse formato do lead nem peça reenvio por causa dele. O RG é opcional.
```

### K6, K7, K8. O fluxo do endereço pergunta número e complemento sempre (achado 2)

Problema: sc03 T21, a lead manda "Rua das Paineiras 418 ... Cep: ...". A IA responde "Buscamos nos Correios..." e
"Por favor, me informe o número do imóvel." No T22, "como eu falei, mandei ali em cima, é 418". A "REGRA DE REFORÇO",
que "sobrescreve qualquer outra instrução", manda perguntar Número e Complemento depois do CEP, e isso derruba o
"Perguntar apenas o que faltar".

K6 — ANTES (seção ENDEREÇO):
```
Se Sim: Pergunte o número e complemento caso tenho
```
K6 — DEPOIS:
```
Se Sim: Pergunte o número e complemento caso tenho (só o que o lead ainda não informou)
```
K7 — ANTES (REGRA DE REFORÇO, 3a):
```
- Perguntar o Número.
- Perguntar o Complemento.
```
K7 — DEPOIS:
```
- Perguntar o Número (só se o lead ainda não informou).
- Perguntar o Complemento (só se o lead ainda não informou).
```
K8 — ANTES (REGRA DE REFORÇO, 3b):
```
- Perguntar separadamente, um por vez:
```
K8 — DEPOIS:
```
- Perguntar separadamente, um por vez, só o que o lead ainda não informou:
```
Ressalva do achado: não está provado que `numero_casa=418` já estava em "DADOS JÁ INFORMADOS" no T21 (o resultado não
grava os fatos por turno). Se não estava, a causa é o extrator, e esta troca não basta (ver pendências).

---

## ASSINATURA

### A1. Conflito conhecido: a FAQ manda imprimir (sc02, reprovação esperada)

Problema: a assinatura é digital (ZapSign), mas a FAQ responde "Sim, é necessário imprimir todas as páginas, assinar e
depois enviar a foto". É a origem do erro do CHAT 2, e o sc02 reprova de propósito até o escritório corrigir a linha
(NOTAS, "Decisões do fechamento").

ANTES:
```
-Preciso imprimir todas as folhas? → “Sim, é necessário imprimir todas as páginas, assinar e depois enviar a foto para nossa equipe.”
```
DEPOIS:
```
-Preciso imprimir todas as folhas? → “Não precisa imprimir nada: a assinatura é feita pelo celular, no próprio link que você recebeu.”
```
A resposta nova atende ao `obrigatorio_em.assinatura` do sc02 ("pelo celular", "não precisa ... imprim") e não cai nos
proibidos (a frase tem "não").

---

## DESQUALIFICADO

### D1, D2. O resumo não tem vaga para o motivo real (achado 15)

Problema: sc15[saiu_ha_mais_de_3_anos] T7 diz "...estando você como MEI manicure e não tendo recebido auxílio-doença, esse
benefício não se aplica", e sc17[sem_documentos] T6 diz "...trabalhador rural sem carteira assinada e não tendo recebido
auxílio-doença". O motivo real (anos sem carteira antes do acidente; nenhuma prova rural da época) não aparece, e o texto
sugere que ser MEI ou não ter recebido auxílio-doença é o motivo. O OBJETIVO manda "Explicar ... o motivo", mas o modelo
de resumo não tem vaga para isso.

D1 — ANTES:
```
Pelo que você me contou — acidente [ocorrido em…], do tipo [tipo…], com sequelas [sequelas…], estando você [situação de trabalho…] e [tendo/não tendo] recebido auxílio-doença [período…] —, esse benefício não se aplica ao seu caso;
```
D1 — DEPOIS (o resto da frase, "só quero confirmar se entendi tudo certo...", continua igual):
```
Pelo que você me contou — acidente [ocorrido em: ano informado pelo lead, ou "ano não informado"], do tipo [tipo…], com sequelas [sequelas…], estando você [situação de trabalho…] e [tendo/não tendo] recebido auxílio-doença [período…] —, como [motivo real: ex. "fazia tempo demais que você estava sem carteira assinada antes do acidente" / "não há documento da época que prove o trabalho rural" / "você já recebe auxílio-acidente"], esse benefício não se aplica ao seu caso;
```
D2 — inserir logo depois desse parágrafo, antes de "Se a pessoa disser que a situação mudou...":
```
No [motivo real], diga a trava que de fato desqualificou o lead. Nunca apresente como motivo o que não é trava: ser MEI por si só, ou não ter recebido auxílio-doença, não desqualifica ninguém.
```

---

## O que ficou fora do prompt (outras áreas)

- **Checagem `varias_perguntas` (achados 0, 3, 9)**: não muda. Isentar frases do roteiro esconderia o conflito com a regra
  de uma pergunta por vez, que a correção resolve no prompt (K1, K2, S6).
- **Cartão do sc14 (achado 6, item 3)**: criar um assunto de demissão antes do assunto "registrad", com um regex que case
  com a 5.1. A versão do sugerido (S6) diz "tinha saído da última empresa", então
  `(?i)demiss|sa[íi]d[oa] d[ao]|sa[íi]u d[ao]|[úu]ltim[oa] (empresa|emprego)` casa com as duas versões. Resposta: "nunca
  fui demitido, to no mercado desde 2021 ate hoje".
- **sc18 sem `perguntar_antes` do ano (achado 7)**: `{"closer": ["(?i)\\b(qual|que) ano\\b|\\bano\\b[^?]{0,40}acident"]}`.
  Esse regex casa com "Em que mês e ano aconteceu o acidente?" (S1) e não casa com a pergunta da CLT.
- **Motor**: o rótulo "DADOS DO ESCRITÓRIO (use quando perguntarem)" em `agente.montar_conhecimento` puxa contra o envio
  espontâneo (achado 10); o reforço "transferir_para quando o closer pede dado de coleta" (achado 1); gravar
  `fatos_depois` e o conteúdo por turno no `resultado.json` (achados 2 e 14).
- **Juiz** (achados 15, 16): perguntar se o motivo dito ao lead é o motivo real da desqualificação, e se a IA fez
  avaliação jurídica ou previsão de dificuldade que o prompt não manda.
