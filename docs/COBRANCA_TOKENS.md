# Cobrança da IA em reais (saldo, bônus e consumo)

25/11/2026. Como o LawChat IA cobra o uso da inteligência artificial de cada escritório, no mesmo modelo do Weaver. Este texto é para o dono: o que foi decidido, como a conta é feita, onde cada coisa aparece no painel e o que ainda falta fazer.

Arquivos principais: `db/migracoes/007_agentesia_cobranca.sql` (e `desfazer_007.sql`), `app/cobranca/` (`__init__.py`, `gateways.py` e `rotas.py`), as telas `painel/src/telas/Carteira.tsx` e `AdminCobranca.tsx`, e os testes em `tests/test_cobranca.py`.

---

## 1. O modelo em uma página

- **Uma chave de IA só, a da LawChat.** Ela fica no `.env` do servidor (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`). A opção de o escritório usar a própria chave da OpenAI saiu do painel e do motor. Se algum escritório tinha uma chave salva, ela continua guardada (não foi apagada), mas é ignorada.
- **Cada escritório tem uma carteira**, com duas partes:
  - **saldo (R$)**: recargas pagas, bônus dados pela LawChat e ajustes. Não expira.
  - **bônus do mês (R$)**: vem do plano e é renovado todo mês. Por padrão, o que sobra não passa para o mês seguinte. Isso pode ser mudado em cada plano.
- **Toda chamada de IA é registrada.** Entram aí: a conversa (etapa), a leitura da mensagem (extrator), o revisor, imagem, PDF, áudio, a base de conhecimento (embeddings), o follow-up e os resumos. Cada chamada grava os tokens, o custo em US$, a cotação e o markup daquele momento, o custo em R$, o valor cobrado, o escritório, o lead, o agente e a etapa.
- **O débito sai em lote, a cada minuto.** Primeiro gasta o bônus do mês, depois o saldo. Cada débito vira uma linha no **livro de movimentos**. O saldo da carteira é sempre igual à soma do livro, e o banco não deixa mexer no saldo por fora do livro.
- **Quando o disponível chega a zero, a IA do escritório pausa.** O motivo registrado é `sem_saldo`. O cliente vê o aviso em todas as telas e pode pedir recarga. Quando o crédito entra, a IA volta sozinha.

---

## 2. As fórmulas

### 2.1 Custo de uma chamada em US$ (app/modelo.py)

```
custo_usd = ( entrada × preço_entrada
            + saída × preço_saída
            + cache_lido × preço_cache
            + cache_gravado × preço_entrada × 1,25 ) ÷ 1.000.000
```

- Os preços estão em `PRECOS_USD_POR_MILHAO`, em US$ por milhão de tokens.
- A gravação de cache (`cache_gravado`) só existe na Anthropic e é cobrada a 1,25 vez a entrada.
- Transcrição de áudio usa o uso informado pela OpenAI. Se ele não vier, o custo é estimado pela duração do áudio.

### 2.2 De dólar para real, com markup (feito pelo banco, no momento em que a chamada é gravada)

```
custo_brl_real = custo_usd × cotação
custo_brl      = custo_usd × cotação × markup      ← é este valor que sai da carteira
```

- **Cotação**: quantos reais vale um dólar. Começa em **5,50**, o mesmo valor do nó de tokens do n8n.
- **Markup**: um multiplicador. **1,00** cobra só o custo. **1,30** cobra 30% a mais. Começa em **1,00**, também como no n8n.
- Cada chamada guarda a cotação e o markup que estavam valendo quando ela foi feita. Mudar a cotação hoje não muda o que já foi cobrado.

### 2.3 Exemplo numérico

Cotação 5,50 e markup 1,30 (+30%). Uma resposta da conversa com `gpt-4.1` usou 3.000 tokens de entrada (1.000 deles vindos do cache) e 300 tokens de saída.

| Passo | Conta | Valor |
|---|---|---|
| Custo em US$ | (2.000 × 2,00 + 300 × 8,00 + 1.000 × 0,50) ÷ 1.000.000 | US$ 0,0069 |
| Custo real em R$ | 0,0069 × 5,50 | R$ 0,03795 |
| Valor cobrado | 0,03795 × 1,30 | R$ 0,049335 |
| Margem da LawChat | 0,049335 − 0,03795 | R$ 0,011385 |

Um turno costuma ter 2 ou 3 chamadas: leitura da mensagem, conversa e, às vezes, o revisor. Com números parecidos, isso dá uns R$ 0,06 a R$ 0,08 por resposta.

### 2.4 O que é "disponível" e quando a IA pausa

```
disponível = saldo + bônus do mês − consumo já gravado e ainda não debitado
```

- **Modo "pré-pago"**: com disponível ≤ 0, nenhuma chamada paga sai.
- **Modo "só registrar"**: a IA nunca pausa. O consumo é registrado e debitado do mesmo jeito, e o saldo pode ficar negativo.

O consumo ainda não debitado já entra na conta. Assim, a IA não continua gastando no minuto entre uma chamada e o débito em lote.

### 2.5 Bônus do mês

Exemplo: plano Básico, R$ 297 por mês, com bônus de R$ 100.

| Momento | O que acontece no livro | Bônus |
|---|---|---|
| Outubro, plano escolhido | + R$ 100 "Bônus do plano (2026-10)" | 100 |
| Consumo de R$ 10 | − R$ 10 "Consumo da IA" (sai do bônus) | 90 |
| 1º de novembro, sem acumular | − R$ 90 "Bônus expirado", depois + R$ 100 "Bônus do plano (2026-11)" | 100 |
| 1º de dezembro, com acumular ligado | + R$ 100 | 200 |

- A renovação roda a cada minuto, mas só vale uma vez por mês e por escritório. A chave é `bonus_plano:<escritório>:<AAAA-MM>`, no horário de Brasília.
- Quando um plano é escolhido para o escritório, o bônus do mês entra na hora.

---

## 3. "Pode gastar?": o bloqueio único

Existe uma função só, `app.cobranca.bloqueado(...)`, que guarda a resposta por 15 segundos. Ela é consultada antes de toda chamada paga:

| Onde | O que acontece sem saldo |
|---|---|
| Turno da conversa (`pipeline._conferir_consumo`) | O turno fica em silêncio com o motivo `sem_saldo`. Vira evento no painel e uma nota no chat da Helena (uma vez a cada 6 h). |
| Leitura de mídia (`pipeline._ler_midia`) | Não transcreve nem descreve. A mensagem fica marcada como "[arquivo não lido: o saldo da IA acabou]". |
| Follow-up (`followup/servico._por_que_nao`) | O follow-up é **cancelado**, não adiado. |
| Resumo da memória e origem do anúncio (fila de ações) | A ação é marcada como feita com o motivo `sem_saldo`, sem chamar a IA. |
| Resumo do contrato assinado | Segue sem o resumo. As automações do contrato assinado disparam normalmente. |
| Base de conhecimento (indexação) | O documento espera em "processando" até o saldo voltar. |

**Volta sem rajada.** Quando o crédito entra, a próxima mensagem do lead é respondida normalmente. O que chegou durante a pausa não é respondido de uma vez: aquelas mensagens já foram fechadas como silêncio, e a equipe pode responder pela Helena. Os follow-ups do período foram cancelados, e a cadência recomeça na próxima resposta da IA.

**Avisos.** Saem pela fila de ações (`aviso_consumo`) e vão para dois lugares: um evento na tela de erros e avisos do painel e um WhatsApp para os números do aviso "Consumo da IA perto do limite". São três avisos:

- **80% do bônus do mês usado**: uma vez por mês;
- **bônus do mês acabou**: uma vez por mês;
- **saldo acabou, IA pausada**: uma vez por pausa. Este também vai para a central de avisos da LawChat.

O limite mensal em US$ que já existia (`config.limite_consumo`) continua funcionando como uma trava extra. Ele é conferido depois do saldo.

---

## 4. As telas

### 4.1 Cliente (gestor): menu Acompanhar › **Consumo e saldo** (`/consumo`)

- **Cartões**: disponível agora, saldo, bônus do mês (com a barra de quanto já foi usado) e consumo do mês, com o nome do plano.
- **Onde a IA gastou**: valor por dia (7, 30 ou 90 dias), por agente, por etapa e por função ("Conversa", "Áudio", "Follow-up"...), sempre em R$.
- **Extrato**: cada movimento com o saldo e o bônus depois dele. Nos débitos de consumo aparece só o número de chamadas.
- **Pedir recarga**: o gestor escolhe o valor (sugestões de R$ 100, 300, 500 e 1.000) e uma observação. O pedido fica pendente e a LawChat é avisada no WhatsApp. Um clique duplo não cria dois pedidos. O gestor pode cancelar um pedido pendente.
- **Faixa vermelha** no topo de todas as telas quando a IA está pausada por saldo. Todos os papéis veem a faixa, mas o botão "Pedir recarga" só aparece para o gestor.
- **O cliente não vê** US$, cotação, markup nem custo real. Tokens e número de chamadas só aparecem se ele marcar a caixa "Detalhe".
- **O atendente** não abre a tela. Ele só vê a faixa de pausa.

### 4.2 Integrações

- O cartão "Chave própria da OpenAI" saiu.
- A rota antiga (`PUT /api/integracoes/openai`) responde 410 e explica por quê.
- Na ativação do agente, só a chave da LawChat conta.

### 4.3 Admin (equipe LawChat): menu LawChat › **Cobrança da IA** (`/admin/cobranca`)

- **Carteiras**:
  - todos os escritórios, com modo, plano, saldo, bônus, valor a debitar, cobrado no mês, custo real, margem e se a IA está pausada;
  - em **Abrir**: trocar o plano, escolher um markup próprio do escritório ou voltar ao global, ligar o pré-pago (com a opção de perdoar o saldo negativo do período "só registrar"), lançar bônus, crédito ou ajuste (sempre com motivo) e ver o livro completo, com o custo em US$;
  - a conferência "carteira = soma do livro" aparece em vermelho se algum dia der diferença.
- **Recargas**: pendentes, pagas e todas, com os botões **Confirmar pagamento** (credita uma vez só) e **Cancelar**.
- **Planos**: criar e editar, com código, nome, preço mensal, bônus mensal, se o bônus acumula e se está ativo.
- **Cotação e markup**: o valor de agora, uma prévia de quanto custa e quanto é cobrado, a mudança com motivo e o histórico.
- **Consumo e margem**: por escritório e por modelo, com chamadas, tokens, custo em US$, custo em R$, cobrado e margem. Também avisa quando há chamadas de modelo sem preço na tabela.

Toda ação do admin fica registrada no Histórico (`agentesia_alteracoes`).

---

## 5. Recarga e pagamento

### 5.1 Como o Weaver faz (só leitura de `agents-lawchat-main`)

**Tabelas e cálculo**

- `sistemaia_saldos` tem uma linha por conta: `saldo_brl`, `total_recarregado_brl`, `total_gasto_brl`, `margem_percentual` (padrão 50%), `tolerancia_negativa_brl` (padrão R$ 20) e `pausado_por_saldo`.
- A cotação fica em `sistemaia_cotacao`. Um cron diário busca o valor numa API pública, com 5,50 de reserva.
- O cron `sistemaia_processar_consumo` roda a cada 2 minutos. Ele lê `consumo_tokens` (gravado pelo n8n), calcula `custo_real = US$ × cotação` e `cobrado = custo_real ÷ (1 − margem)`, grava em `sistemaia_uso` e debita a conta.
- A idempotência vem do `id_consumo_origem` e de `sistemaia_execucoes_cobradas`.

**Pausa**

- Um gatilho no saldo pausa os agentes quando o saldo fica ≤ −tolerância e reativa quando volta.

**Bônus do plano**

- O bônus é `sistemaia_planos.bonus_token_brl`. Ele **acumula** e é creditado no "aniversário" da conta.

**Asaas**

- **`asaas-create-payment`**:
  - recebe Pix ou cartão, de R$ 50 a R$ 50.000, com um bônus de 3% a 18% por faixa de valor;
  - cria a recarga pendente antes de chamar o Asaas;
  - manda `externalReference` = id da recarga e guarda o QR e o copia e cola do Pix.
- **`asaas-webhook`**:
  - confere o token do cabeçalho `asaas-access-token` em tempo constante (o Asaas não assina com HMAC);
  - `PAYMENT_CONFIRMED` ou `RECEIVED` credita uma vez;
  - `REFUNDED` ou chargeback estorna;
  - `OVERDUE` ou `DELETED` marcam falha.
- **`asaas-poll-pending`**: a cada 15 minutos consulta as recargas pendentes, para o caso de um webhook se perder.
- Não há assinatura recorrente do plano: no Weaver só existem recargas avulsas.

### 5.2 Fluxo proposto aqui

```
Cliente: "Pedir recarga" (R$ 300)
   │  agentesia_recargas: pendente, gateway = manual (ou asaas), pedido_por
   │  evento pedido_recarga → central de avisos → WhatsApp da LawChat
   ▼
Gateway gera a cobrança
   │  manual: a LawChat manda Pix ou boleto por fora
   │  asaas (depois): POST /v3/payments com externalReference = id da recarga →
   │                  id_externo, url_pagamento, pix_copia_cola, pix_qr_base64, vencimento
   ▼
Pagamento confirmado
   │  manual: admin › Recargas › "Confirmar pagamento"
   │  asaas: POST /api/pagamentos/asaas/webhook (token no cabeçalho) → agentesia_pagamento_eventos
   ▼
agentesia_confirmar_recarga: trava a recarga, lança + R$ 300 no livro (chave recarga:<id>) e marca "paga"
   │  repetir (webhook duplicado, clique duplo) devolve o mesmo movimento: não credita de novo
   ▼
Carteira positiva → pausado_por_saldo = false → a IA volta na próxima mensagem do lead
```

Outras situações da recarga:

- **Estorno**: `agentesia_estornar_recarga` tira o valor uma vez só, e a recarga vira "estornada".
- **Expirada ou cancelada**: a recarga só muda de situação, sem mexer no dinheiro.

### 5.3 As tabelas da migração 007

| Tabela | Para quê |
|---|---|
| `agentesia_cobranca_config` | Cotação e markup globais, com histórico, quem mudou e o motivo |
| `agentesia_planos` | Código, nome, preço mensal, bônus mensal, se o bônus acumula, se está ativo |
| `agentesia_carteiras` | Uma por escritório: plano, modo, saldo, bônus, bônus do mês, markup próprio, pausa, avisos já mandados |
| `agentesia_carteira_movimentos` | **O livro**: tipo, valor, parte no saldo e parte no bônus, saldo e bônus depois, chave única, motivo, quem, recarga. Não pode ser alterado |
| `agentesia_chamadas_ia` (colunas novas) | Tokens de cache, lead, agente, etapa, origem, sem preço, cotação, markup, custo em R$ (real e cobrado), situação da cobrança (pendente, debitada ou isenta) e o movimento que debitou |
| `agentesia_recargas` | Valor, situação (pendente, paga, cancelada, expirada, estornada), gateway, método, id externo, link, Pix copia e cola e QR, vencimento, quem pediu, quem confirmou, movimento |
| `agentesia_pagamento_eventos` | Webhooks recebidos. O par (gateway, id do evento) é único, então o mesmo evento não é processado duas vezes |
| `agentesia_assinaturas` | **Prevista**: plano com cobrança recorrente (situação, ciclo, valor, gateway, id externo, próxima cobrança). Hoje a mensalidade é cobrada por fora |

Funções do banco:

- `agentesia_carteira_lancar`: o único jeito de mudar saldo e bônus;
- `agentesia_debitar_consumo`: débito em lote;
- `agentesia_confirmar_recarga` e `agentesia_estornar_recarga`;
- `agentesia_renovar_bonus`;
- `agentesia_cobranca_vigente`;
- a view `agentesia_v_carteira_conferencia`.

Essas funções não podem ser chamadas pela API pública do Supabase.

### 5.4 O que falta para ligar o Asaas

1. **Conta e chaves.** Pôr `ASAAS_API_KEY` e `AGENTESIA_ASAAS_WEBHOOK_TOKEN` no `.env`, primeiro em sandbox e depois em produção. Definir `AGENTESIA_GATEWAY_RECARGA=asaas`.
2. **`GatewayAsaas.criar_cobranca`** (em `app/cobranca/gateways.py`, hoje responde "não implementado" e o pedido cai no manual):
   - buscar ou criar o cliente (`/v3/customers`, pelo CNPJ ou CPF do escritório; falta guardar o documento do escritório);
   - criar a cobrança com `POST /v3/payments` (billingType PIX ou BOLETO, `externalReference` = id da recarga, vencimento);
   - buscar o QR em `GET /v3/payments/{id}/pixQrCode`.
3. **Webhook no Asaas.** Cadastrar `https://<servidor>/api/pagamentos/asaas/webhook`, com o token, para os eventos de cobrança. A rota e o processamento já existem e foram testados com dados falsos: credita uma vez, ignora o evento repetido, estorna e marca expirada ou cancelada.
4. **Conferência periódica**, como o `asaas-poll-pending` do Weaver, para quando um webhook se perder: um laço que consulta `GET /v3/payments/{id}` das recargas pendentes.
5. **Tela do cliente**: mostrar o QR do Pix e o boleto (os campos já vêm na API) e a contagem do vencimento.
6. **Mensalidade do plano (recorrente).** `POST /v3/subscriptions`, gravando em `agentesia_assinaturas`. O webhook da assinatura atualiza a situação. Falta decidir se uma mensalidade atrasada também pausa a IA.
7. **Decisões comerciais pendentes**: bônus por faixa de recarga (o Weaver dá de 3% a 18%), valor mínimo da recarga, cartão de crédito e nota fiscal.

---

## 6. O que ficou configurável

| Decisão | Padrão | Onde muda |
|---|---|---|
| Cotação US$ → R$ | 5,50 | Admin › Cobrança › Cotação e markup (com histórico) |
| Markup global | 1,00 (sem margem) | Mesma tela, em % sobre o custo |
| Markup de um escritório | o global | Admin › Carteiras › Abrir |
| Bônus do plano acumula? | Não (o que sobra expira no fim do mês) | Admin › Planos, em cada plano |
| Modo da carteira | Escritórios que já existiam e os novos começam em **"só registrar"** (a IA não pausa) | Admin › Carteiras › "Ligar pré-pago" |
| Perdoar o negativo ao ligar o pré-pago | O admin escolhe na hora | Pergunta ao ligar |
| Bônus manual da LawChat | Entra no saldo e não expira | — |
| Intervalo do débito em lote | 60 s | `AGENTESIA_COBRANCA_INTERVALO_S` |
| Gateway da recarga | manual | `AGENTESIA_GATEWAY_RECARGA` (manual ou asaas) |
| Limite mensal em US$ (o que já existia) | Continua como trava extra | Admin › Escritórios › limite |

**Por que os escritórios começam em "só registrar".** Se começassem no pré-pago, todos os escritórios atuais parariam de responder no momento em que a migração fosse aplicada, já que nenhum tem saldo ainda. O caminho é este:

1. aplicar a 007;
2. criar os planos;
3. escolher o plano de cada escritório (o bônus entra na hora);
4. ligar o pré-pago, perdoando o negativo se for o caso.

---

## 7. Pendências e cuidados

- **Pagamento online**: a estrutura está pronta, mas a chamada ao Asaas não está ligada (seção 5.4).
- **Preços a conferir** em `app/modelo.py`:
  - o cache da família GPT-6 foi estimado em 1/4 da entrada;
  - o `gpt-6-luna` antes contava custo zero e agora tem o preço da tabela do Weaver.
  - Chamadas com tokens e custo zero ficam marcadas como "sem preço" e aparecem em Admin › Consumo e margem. **Essas chamadas não são cobradas.**
- **Histórico anterior à 007**: o R$ foi calculado com a cotação inicial só para relatório, e essas chamadas ficaram como "isenta". Nada antigo foi cobrado.
- **Laboratório do agente** (simulação no painel): roda em memória e não é cobrado.
- **Concorrência**: o débito usa "skip locked" e o crédito usa chave única. Os testes provam que nada é debitado ou creditado duas vezes, mesmo com várias chamadas ao mesmo tempo. O banco local de teste tem uma conexão só, então a corrida real entre dois servidores fica garantida pelo Postgres, não pelo teste.
- **Não houve** chamada a API real, commit nem migração aplicada em produção.
