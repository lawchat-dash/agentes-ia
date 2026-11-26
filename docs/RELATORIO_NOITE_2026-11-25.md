# Relatório da noite (25/11/2026): teste do Auxílio-Acidente do Sousa e Costa

O pedido foi testar do início ao fim o prompt de Auxílio-Acidente do Sousa e Costa, com o fluxo n8n real, os 3 chats reais
como base, gpt-4.1-mini a 0.5 e no máximo US$ 2. O teste cobriu prompt, ferramentas, conferências e trocas de etapa
(SDR → Período de Graça → Closer → Contrato → Assinatura → Contrato assinado / Desqualificado). Também foi pedido corrigir
o que estivesse errado.

**Gasto: US$ 1,95 de US$ 2,00.** Os US$ 0,50 da rodada aprovada antes não entram nessa conta. Nada foi commitado.
Os chats reais ficaram só no scratchpad da sessão, e os cenários usam pessoas, documentos e endereços inventados. Uma
varredura automática não achou CPF, RG, CEP, e-mail ou link dos chats nos arquivos do projeto.

## 1. O que foi montado

| Arquivo | O que é |
|---|---|
| `avaliacao/agentes/sousa_costa.json` | Os 6 prompts reais do fluxo n8n convertidos para o motor, sem mudar o texto do escritório. As conversões estão em `sousa_costa_NOTAS.md` |
| `avaliacao/agentes/sousa_costa_sugerido.json` | O mesmo, com 33 correções mínimas de texto (abaixo) |
| `avaliacao/agentes/sousa_costa_RECOMENDACOES.md` | Cada correção com o texto **ANTES** e **DEPOIS**, pronta para colar no n8n ou no painel |
| `avaliacao/cenarios_sousa_costa/` | 23 casos: sc01–sc03 vêm dos 3 chats (anonimizados e com os fatos alterados), sc10–sc19 são as variações (sem e-mail, CEP não encontrado, advogado, aposentado, MEI, desempregado, rural, vídeo/áudio/não sabe ler, preço) e sc20 é o CPF com pontuação torta |
| `avaliacao/agentes/catalogo_referencia_RECOMENDACOES.md` | O mesmo trabalho para o agente de catálogo de referência |

Para rodar: `python -m app.avaliacao rodar --real --juiz --rodadas 1 --teto-usd X --cenarios avaliacao/cenarios_sousa_costa --agente avaliacao/agentes/sousa_costa.json`.
Uma bateria completa de 1 rodada custa uns **US$ 0,60** de verdade. O `estimar` costuma dar uns 4× mais.

## 2. Rodadas reais

| Rodada | Prompt | Motor | Resultado | Custo |
|---|---|---|---|---|
| Catálogo (todos) | referência | antes das correções da noite | 2/8 | 0,17 |
| Sousa e Costa (22 casos) | **fiel** | antes | **6/22** | 0,60 |
| Sousa e Costa (15 que reprovaram) | **fiel** | corrigido (1ª leva) | 5/15 ok, 2 cortados pelo teto | 0,60 |
| Catálogo (01, 03, 04, 06) | referência | corrigido (1ª leva) | 1 ok, 06 cortado | 0,10 |
| Sousa e Costa (10 piores) | **sugerido** | corrigido e revisado | 2/10 ok, sc20 cortado | 0,40 |
| Catálogo (03, 04, 06) | referência | corrigido e revisado | 03 com e sem seguro ok, 04/06 cortados | 0,08 |

Passaram pelo menos uma vez **14 dos 22 casos**:
- sc10 (sem e-mail);
- sc12 (advogado, as 3 variantes);
- sc13 (já recebe auxílio-acidente);
- sc15 (as 3 variantes);
- sc16 (com e sem seguro);
- sc17 (rural, as 2 variantes);
- sc18 (pede áudio / não sabe ler);
- sc19 (preço).

Nunca passaram:
- sc01, sc02 e sc03 (os 3 chats reais);
- sc11 (CEP não encontrado);
- sc13 (aposentada por invalidez);
- sc14 (acidente fora do trabalho);
- sc18 (videochamada);
- sc20, que foi cortado nas duas vezes.

Atenção: cada caso rodou 1 vez por rodada. Com temperatura 0.5 isso tem ruído, e um caso que passou uma vez ainda
precisa de 3 rodadas para virar confiável.

Relatórios e transcrições: `avaliacao/resultados/2026-11-25_0317_*`, `_0426_*`, `_0523_*` (Sousa e Costa) e `_0146_*`, `_0417_*`,
`_0518_*` (catálogo).

## 3. O prompt do Sousa e Costa, etapa por etapa

### SDR
- **Acerta:** acolhe o relato com empatia e manda as mídias do roteiro. Desqualifica certo o aposentado, quem já recebe
  auxílio-acidente e quem tem advogado atuando hoje, e manda "quer trocar de advogado" para análise humana. Não
  desqualifica quem se acidentou fora do trabalho (a regra do prompt).
- **Erra:**
  - **Pula a pergunta do ano do acidente** (só 1 de 22 conversas perguntou). Causa: o corpo da pergunta 2 é cópia do
    corpo da pergunta 1. Correção S1.
  - Trata "sou registrado/fichado" ora como CLT (vai para o closer), ora como período de graça. A pergunta 5.1 é usada
    com quem é CLT e tem 2 perguntas numa mensagem. Correções S3–S6 e S11.
  - **Conflito interno:** a 5.1 diz que quem saiu há mais de 3 anos vai para desqualificado, e as TRAVAS dizem que quem
    teve CLT antes vai para período de graça. Correções S7, S9 e S10: o escritório precisa decidir qual vale.
  - Dá opinião jurídica: "não ter recebido auxílio-doença pode complicar". Correção S2.
  - Às vezes passa para o closer **sem** "Maravilha! Nós podemos te ajudar no seu caso." Foram 4 de 10 na última
    rodada; a frase está no prompt e o modelo omite. O motor já tem uma trava para isso, mas ela só liga por
    configuração (ver decisões).

### Período de Graça
- **Acerta, depois das correções:** faz a conta dos meses e decide certo com e sem seguro-desemprego (sc16 e sc17 passaram).
- **Erra no prompt fiel:**
  - Presume que a data do acidente já foi dita.
  - Pergunta da CLT 3 vezes a quem disse "nunca".
  - "Refazer a pergunta até obter mês e ano" não tem saída para "não sei" nem para "nunca fui demitido", e isso vira
    laço (sc14).
  - Anuncia "agora vou calcular" e para.
  - Correções P1–P8.

### Closer
- **Acerta:** segue as etapas, manda os vídeos e responde golpe, preço e família pelo roteiro.
- **Erra:**
  - A ETAPA 5 manda acionar contratos **duas vezes**, e por isso o closer pede o nome antes da hora (sc03, mesmo com o
    sugerido). Correção C1.
  - A OBJ 4 conflita com a regra 6 sobre enviar os dados do escritório. Correções C2 e C3; o sc19 passou com elas.
  - Escreve "garantir seu direito / o melhor resultado". A trava barra e manda refazer, e no sc11 isso aconteceu 2
    vezes e o lead foi **pausado**. Vale pôr no prompt "nunca use 'garantir'".

### Contrato
- **Erros que eram do motor e foram corrigidos:**
  - Dizia que um CPF válido estava "incorreto" e ficava em laço (sc01, sc10). O n8n tinha a BUSCARCPF; o motor agora
    confere o CPF e manda o resultado para a IA.
  - Inventava o endereço "Buscamos nos Correios" sem ter buscado (sc02, sc11). A busca do CEP agora roda no mesmo
    turno, e uma trava pega o endereço sem fonte.
- **Erra no prompt:**
  - A confirmação final tem 3 "?" numa mensagem só. Correções K1 e K2.
  - Pergunta de novo o número ou o complemento que o lead já mandou. Correções K6–K8; ainda aparece no sc02.
  - Promete que a lesão nova "entra no processo" ("podemos incluir sim") no sc03. É promessa: o prompt precisa dizer
    que quem avalia é o advogado.

### Assinatura
- **Erro grave do prompt (A1):** a FAQ diz "Sim, é necessário imprimir todas as páginas, assinar e enviar a foto". Foi
  exatamente o erro do chat real 2, e a IA repetiu na rodada. **Corrigir no n8n já.**
- Quando o código de assinatura não chega (sc01), a IA fica perguntando "conseguiu abrir o link?" até o limite de 32
  turnos, sem passar para a equipe. O sinal `dificuldade_assinatura` não disparou. O prompt deve mandar passar para a
  equipe já na 2ª dificuldade.

### Desqualificado
- O resumo não tem lugar para o **motivo real** da desqualificação, e a IA põe um motivo errado. Ela também pede a
  confirmação e a nota no mesmo balão. Correções D1 e D2.

## 4. O que eu corrigi no código (vale para todos os escritórios)

Motor de produção (`app/cerebro`, `app/pipeline.py`, `app/contrato/dados.py`):
- **CPF conferido no turno**, como a antiga BUSCARCPF. O CPF válido é regravado formatado e a IA recebe a linha
  "CONFERÊNCIA DO CPF (sistema)".
- **CEP:**
  - O motor captura o CEP mesmo sem rótulo e busca no mesmo turno, com a linha "BUSCA DE CEP (sistema)".
  - Um CEP corrigido refaz a busca.
  - Se a rede falha, isso não vira "CEP não encontrado" para sempre.
  - CEP geral da cidade mantém a cidade e a UF.
- **Promessa:**
  - "100% online" e "você vai receber o link/contrato/contato" passam.
  - "garantir o benefício" e "você vai receber os atrasados" continuam barrados.
  - "Você tem direito?" em pergunta não conta.
- **Travas novas, todas leves.** Elas mandam a IA refazer e registram o evento, mas **não pausam** o lead:
  - CPF válido dito errado;
  - resposta repetida em laço;
  - endereço inventado;
  - frase de passagem de outro destino;
  - desqualificar no Período de Graça quem está coberto.
  - Se quiser que as de repetição pausem, ligue `turno.PAUSAR_EM_REPETICAO`. Desliguei de propósito: a revisão achou
    muitos falsos positivos.
- **Eco de confirmação:** a regra antiga do catálogo dava como exemplo "..., certo?", e a IA passou a devolver como
  pergunta tudo o que o lead dizia, fazendo 2 perguntas por balão. A regra foi reescrita.
- A instrução do contrato não diz mais "o link chega em instantes".
- Uma revisão adversarial achou e corrigiu **41 bugs** nessas mudanças. Exemplos: pausar quem pede o CPF do menor, CPF
  com pontos lido como novo pedido, RG confundido com CEP, endereço do escritório tratado como inventado.

Sistema de teste (`app/avaliacao`):
- **Falsos alarmes:** cerca de 30 corrigidos, entre eles:
  - "100% online" lido como honorário;
  - confirmação refeita contada como pergunta repetida;
  - CPF e CEP comparados com a pontuação;
  - mídias que não apareciam na transcrição;
  - uma conversa cortada por laço gerava 6 falhas em cascata.
- A CLI ganhou `--cenarios` e `--agente`, e a estimativa ficou mais realista.

**Testes: 870 passaram, 56 foram pulados** (os pulados precisam de Postgres ou cassete) e nenhum falhou.

## 5. O que você precisa decidir ou fazer

1. **Corrigir a FAQ de imprimir na Assinatura do Sousa e Costa** (A1, em `sousa_costa_RECOMENDACOES.md`). É urgente:
   está acontecendo com lead real.
2. Aplicar no n8n ou no painel as outras correções de prompt do `RECOMENDACOES.md`. As de maior efeito são S1 (ano do
   acidente), C1 (contratos duas vezes), K1/K2 (3 perguntas) e P1–P8 (período de graça). Também é preciso decidir o
   conflito S7/S9/S10 (mais de 3 anos: desqualificado ou período de graça?).
3. Ligar a trava de frase obrigatória para o closer e o contrato do Sousa e Costa. É só configuração:
   `papeis.closer.exigir_frase_de_troca = true` e o mesmo em `contratos`. Ainda não foi medido em rodada real.
4. Decidir a trava de "garantir":
   - deixar como está, rígida: ela refaz a resposta e, se a IA repetir, pausa;
   - ou liberar frases de serviço como "garantir o melhor atendimento".
5. Rodar 3 rodadas da bateria inteira com o prompt corrigido (uns US$ 1,80) para ter números confiáveis.
6. Pendências de antes, que continuam:
   - aplicar a migração 002 (agora com `agentesia_lead_resumo`);
   - configurar `dominio_helena` por escritório;
   - **trocar o token do Supabase e a chave da OpenAI**;
   - fazer o commit, porque nada foi commitado.
