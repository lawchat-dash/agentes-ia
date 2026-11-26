# Agente próprio e sistema de ferramentas

22/11/2026. Como o cliente monta o próprio agente do zero, e como ferramentas e automações funcionam sem a IA "chamar tools".

## 1. A ideia central: a IA conversa, o código age

No n8n a IA decide sozinha quando chamar cada ferramenta e erra de três jeitos: esquece, chama a errada ou preenche errado. Aqui a IA faz só duas coisas, sempre no mesmo formato:

1. **Extrai** o que o lead disse, preenchendo campos definidos (cada um com o trecho que prova).
2. **Escreve** a próxima mensagem, sabendo o que já se sabe e o que falta perguntar.

Todo o resto (trocar de etapa, mover card, etiquetar, avisar, transferir, gerar contrato) é decidido por **regras** que o cliente monta no painel e o código executa. A "ferramenta" deixa de ser uma decisão da IA e vira uma consequência de um fato.

## 2. Dois tipos de agente

| Tipo | Quem define as regras | Exemplo |
|---|---|---|
| **Pronto** | A LawChat, em código, com as regras jurídicas validadas | Auxílio-Acidente (qualificação, período de graça com datas aproximadas) |
| **Próprio** | O cliente, no painel, sem programar | Triagem de trabalhista, agendamento de consulta, pós-venda |

Os dois usam o mesmo motor: extrator, agente da etapa, travas, automações, laboratório, ativação. Só muda de onde vêm os campos, as etapas e as regras.

## 3. O que o cliente monta num agente próprio

### 3.1 Identidade
Nome da persona, objetivo do agente em uma frase, tom ("acolhedor e direto", por exemplo), o que nunca fazer (lista livre que vira trava).

### 3.2 Campos (o que a IA precisa descobrir)
| Tipo | Exemplo | O que o código garante |
|---|---|---|
| Texto | "Como foi o acidente" | Trecho do lead que prova |
| Sim ou não | "Tem carteira assinada" | Só `sim` ou `nao` |
| Escolha | "Situação de trabalho": CLT, autônomo, desempregado | Só uma das opções |
| Número | "Idade" | Número no intervalo definido |
| Data | "Data da demissão" (aceita aproximada) | Mês e ano válidos |

Cada campo tem uma descrição para a IA ("pergunte de forma simples se...") e diz em qual etapa é perguntado.

### 3.3 Etapas
Lista ordenada. Cada etapa tem:
- **Objetivo e instrução** (o prompt da etapa);
- **Campos da etapa**: a IA pergunta um por vez, na ordem;
- **Tipo**: conversa, ou encerramento (manda a mensagem de passagem e sai).

### 3.4 Regras de passagem (decididas pelo código, na ordem)
Montadas com seletores, sem programar:
- *Quando* **[campo] [é | não é | maior que | menor que | foi respondido]** **[valor]** → *ir para* **[etapa]**.
- *Quando* **todos os campos da etapa forem respondidos** → *ir para* **[etapa]**.
- *Quando* **o lead pedir [intenção]** → *ir para* **[etapa]**.

A primeira regra que valer decide. Sem regra válida, o lead fica na etapa e a IA pergunta o próximo campo.

### 3.5 Intenções próprias
Além das fixas (pedir humano, pedir para parar, engano, aceitar proposta), o cliente cria intenções: "quer agendar visita", "perguntou preço". O extrator marca quando o lead disser com as próprias palavras; regras e automações usam como gatilho.

## 4. Ferramentas (as "tools" de cada etapa)

Ferramenta = ação do sistema ligada a um gatilho. O cliente liga na etapa, sem a IA precisar lembrar:

| Ferramenta | Gatilhos típicos | Situação |
|---|---|---|
| Mover card no CRM da Helena | Lead novo; entrou na etapa | Pronta |
| Etiquetar o contato | Entrou na etapa; intenção | Pronta |
| Nota no atendimento | Sinal, intenção, caso para análise | Pronta |
| Passar para a equipe (transferir) | Pediu humano; análise manual | Pronta |
| Enviar mídia da biblioteca | Entrou na etapa (vídeo de boas-vindas, áudio explicativo) | Próxima |
| Completar endereço pelo CEP | Campo "CEP" respondido | Próxima |
| Gerar contrato na ZapSign | Todos os campos do contrato respondidos e confirmados | Próxima |
| Agendar lembrete (follow-up) | Lead parou de responder na etapa | Próxima |
| Chamar um webhook do cliente | Qualquer gatilho (integração com o sistema do escritório) | Próxima |

Toda ferramenta roda pela **fila de ações**: nunca trava a conversa, repete quando falha (1, 5, 30, 120 minutos) e, se não der, vira um erro na tela Erros com o responsável (cliente, cadastro, provedor).

## 5. Como fica no painel

**Agentes > Novo agente** abre o assistente:
1. **Modelo**: escolher um agente pronto (Auxílio-Acidente) ou "Começar do zero".
2. **Número**: lista os números da Helena (sincronizados, com nome e tipo do canal) e mostra quais já têm agente.
3. **Identidade**: nome, objetivo, tom, modelo de IA.
4. **Campos e etapas** (só no "do zero"): editor visual; no agente pronto mostra as etapas fixas.
5. **Instruções**: o texto de cada etapa, com o padrão ao lado.
6. **Ferramentas e automações**: "quando isto acontecer, faça aquilo", por etapa.
7. **Testar**: o Laboratório com a configuração do rascunho.
8. **Ativar**: números de teste, ativar em teste, ativar para todos.

Tudo continua editável depois, inclusive em agentes que já estão rodando. Cada mudança fica no histórico.

## 6. Como está no código

| Parte | Arquivo |
|---|---|
| Interface comum de produto (campos, etapas, regras) | `app/cerebro/produto.py` |
| Agente pronto Auxílio-Acidente | `app/cerebro/auxilio_acidente.py` |
| Agente próprio (definição montada no painel) | `app/cerebro/produto_livre.py` |
| Automações e ferramentas | `app/automacoes.py` (regras) e `app/acoes.py` (executor) |
| Definição salva | `agentesia_agentes.config.definicao` (produto `proprio`) |
