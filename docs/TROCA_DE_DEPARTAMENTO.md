# Troca de departamento (troca de agente) e o "@"

25/11/2026. Para o dono do produto. Explica como o lead passa de um agente para outro (SDR, Closer, Contratos,
Assinatura, Contrato assinado, Desqualificado), o que muda na Helena em cada passo, como era no n8n e como é no nosso
sistema, e o que ainda falta.

Testes que provam cada caso: `tests/test_e2e_troca_departamento.py` (ponta a ponta: webhook da Helena, servidor,
banco local, IA falsa e Helena falsa) e `tests/test_e2e_helena.py`. Nenhum teste chama a Helena, a OpenAI ou a ZapSign
de verdade.

---

## 1. Resumo

- **Quem troca o agente.** A IA (na própria resposta), a geração do contrato (Contratos → Assinatura), a assinatura
  na ZapSign (Assinatura → Contrato assinado) e a equipe (pelo painel ou, **a partir de agora**, arrastando o card no
  CRM da Helena).
- **O que muda na Helena** a cada troca: o card vai para a coluna da etapa nova, a etiqueta da etapa entra e as das
  outras saem, e fica uma nota no atendimento. Tudo isso é configurado por etapa no agente (automação
  `etapa:<etapa>`).
- **O "@" no prompt** é o jeito de quem escreve o roteiro dizer "aqui passa para o agente X". Ele nunca chega ao lead.
- **"@" digitado pelo atendente no chat não existe** (nem no n8n, nem no nosso). Há uma proposta na seção 6.

---

## 2. Como era no sistema antigo (n8n)

Fluxos lidos: `02 - Troca de Departamento` (Weaver), `04 - Troca de Departamento (Geral)` e o resumo em
`CONTEXTO_DO_SISTEMA.md`.

### 2.1 Quem acionava a troca

1. **Uma tool do agente.** Cada agente tinha tools com o nome da etapa de destino:
   - Weaver: SDR tinha `closer`, `periododegraca` e `desqualificado`; Período de Graça tinha `closer` e
     `desqualificado`; Closer tinha `coletadedados` e `desqualificado`. Contrato e Assinatura não trocavam por tool.
   - Geral: `qualificado` (vira Closer), `desqualificado` e `contrato`.
   - A tool chamava o subfluxo "Troca de Departamento" com a etapa pedida (`ProxAgente_Etapa`). O retorno para a IA era
     vazio, de propósito.
2. **A frase de troca (só no Weaver).** Se a IA escrevia a frase de passagem cadastrada
   (`sistemaia_frases_troca`, "Maravilha! Nós podemos te ajudar no seu caso.") e esquecia a tool, o fluxo principal
   chamava a troca mesmo assim. Valia a frase inteira ou 85% das palavras na ordem. O Geral não usava frase.
3. **Contratos → Assinatura e Assinatura → Contrato assinado** eram do fluxo de Contrato (geração do link e aviso de
   assinatura), não da troca.

### 2.2 O que a troca fazia ("Definir departamento")

| Passo | Weaver | Geral |
|---|---|---|
| Banco | Troca a etapa num comando só, com o lead travado. Só avança (sdr → periododegraca → closer → contratos → assinatura → desqualificado); destino terminal recusado; "já estava" não faz nada | Igual, com a trava de 7 mensagens (barrar tool chamada cedo demais); lead com IA desativada, em análise manual ou contrato assinado não é alterado |
| Card | Move **todos** os cards do lead (até 10), cada um na coluna do seu painel, e confere a resposta | Move o card gravado no lead. No Período de Graça o card fica em SDR |
| Etiqueta | Põe a da etapa nova e tira as das outras (só se a nova existir na conta) | Igual; ao ir para o Comercial, uma IA lê a conversa e põe etiquetas de qualificação ("ERA CLT", "POSSUI DOCUMENTOS MÉDICOS"...) |
| Nota no chat | "O departamento do lead foi mudado para X" | Mesmo texto |
| Aviso | Notificação de troca para a equipe | Alerta no grupo do cliente: "Lead qualificado" (Comercial) e "Proposta aceita" (Contrato) |
| Follow-up | Cancelado ao entrar em Desqualificado | — |
| Equipe/departamento e atendente da Helena | **Não mexia.** A troca de agente não transferia o atendimento de equipe nem mudava o responsável | Idem |
| Histórico | `lead_etapa_historico` (trocado, já estava, não permitido, destino inexistente...) | `troca_departamento_historico` |

### 2.3 Proteção contra troca dupla

O caso real foi o ticket TK-1773: na mesma resposta a IA chamou `closer` e, 35 segundos depois, `desqualificado`; as
duas valeram e o lead qualificado ficou desqualificado. A correção do n8n: **a segunda troca é recusada quando o lead
não mandou mensagem nova desde a anterior (até 10 minutos)**, com aviso para alguém conferir. Vale sempre a primeira.

### 2.4 Repescagem do CRM (só Weaver)

Um fluxo separado, a cada 15 minutos: pega as trocas das últimas 48 horas cujo card **não moveu** na Helena, confere se
o lead ainda está naquela etapa e tenta mover de novo (até 6 vezes, com espera crescente). Só mexe em card. Quando
desiste, avisa.

### 2.5 E quando a equipe movia o card na Helena?

**Nada acontecia.** O n8n não ouvia o evento de card movido (`PANEL_CARD_STEP_CHANGE`). Se a equipe arrastava o card
do SDR para o Comercial, a IA continuava respondendo como SDR, porque quem manda é a etapa gravada no banco.

### 2.6 O "@" no sistema antigo

- **No editor de prompt** (o painel que virou o nosso): quem escreve digita "@" e escolhe um chip.
  - `@Agente Closer`, `@Agente Coleta de Dados`, `@Agente Desqualificado`... ao salvar viram "acionar tool `closer`"
    (o nome da tool do n8n).
  - `@Transferência: Closer` (chip laranja) vira o **texto exato** da frase de entrada do Closer, que o agente anterior
    fala e que o fluxo compara.
  - `@ZapSign` e `@Buscar CEP` viram "acionar tool `zapsign`/`buscarcep`".
- **No chat, pelo atendente:** não existia. O fluxo principal só sabia que um humano falou (e pausava a IA). Não havia
  comando "@closer" nem "@IA" na conversa.

---

## 3. Como funciona no nosso sistema

### 3.1 A IA troca de agente (passo a passo)

1. **Destinos possíveis.** Para cada agente, o motor monta a lista de destinos: os da configuração do papel mais os
   chips do roteiro (`@Agente X`, `@Transferência: X` e "acionar tool `x`"). Regras: só para frente no funil;
   Desqualificado vale sempre; Contratos não passa para Assinatura (quem faz isso é a geração do contrato); o
   Desqualificado pode devolver ao SDR uma vez por conversa.
2. **A IA responde num formato fechado.** A resposta tem **um** campo `transferir_para`, que só aceita os destinos da
   lista (ou vazio). Por isso o caso do TK-1773 (duas trocas na mesma resposta) não tem como acontecer.
3. **Conferências antes de valer:**
   - troca na primeira resposta da conversa é recusada ("tool fantasma");
   - destino fora da lista é recusado e registrado (`destino_recusado`);
   - frase de passagem de **outro** destino na mesma resposta é reprovada e a IA refaz;
   - se a IA escreveu a frase de um destino e esqueceu de marcar, o motor troca pela frase (rede de segurança, como o
     Weaver), e registra `troca_pela_frase`;
   - se marcou e esqueceu a frase, o motor põe a frase de entrada como último balão.
4. **Grava a etapa antes de enviar.** Se nenhuma parte da resposta chegou ao lead (Helena fora), a troca é desfeita:
   o lead não ouviu a frase, continua com o agente antigo.
5. **Depois do envio**, entram na fila as automações da etapa nova (`etapa:closer`, por exemplo): mover o card,
   trocar as etiquetas, nota, aviso à equipe e, se configurado, transferir o atendimento para um departamento. A fila
   tenta de novo em 1, 5, 30 e 120 minutos (é a nossa "repescagem", para card, etiqueta e nota) e, na falha final,
   vira um erro na Central de Avisos.
6. **A próxima mensagem do lead** já é respondida pelo agente novo, com o prompt dele e as boas-vindas dele (se o
   papel tiver).

### 3.2 O que muda na Helena em cada troca

Com as automações que a sugestão do catálogo monta (cada etapa com a sua coluna e a sua etiqueta):

| Troca | Quem faz | Card | Etiquetas | Nota (configurável) | Frase ao lead |
|---|---|---|---|---|---|
| Lead novo | Chegada da 1ª mensagem | Criado na coluna SDR | + 📞 SDR | — | Boas-vindas do SDR |
| SDR → Closer | IA | Coluna do Closer | + 🛒 Comercial, − as outras | "Lead passou para o Closer" | Frase de entrada do Closer |
| Closer → Contratos | IA | Coluna de Contratos | + a de Contratos, − as outras | "Lead passou para Contratos" | Frase de entrada de Contratos (pede o nome) |
| Contratos → Assinatura | Geração do contrato (dados confirmados) | Coluna de Assinatura | + a de Assinatura | Nota + link enviado | O link do contrato |
| Assinatura → Contrato assinado | Aviso da ZapSign (relido no provedor) | Coluna de Assinado | + ✅ Assinado | Nota + resumo do contrato | Confirmação de assinatura; a IA encerra |
| Qualquer → Desqualificado | IA | Coluna de Desqualificado | + ❌ Desqualificado, − as outras | "Lead desqualificado" | Frase de encerramento; follow-up deixa de sair |
| Análise humana | IA (o roteiro diz "Análise da equipe") | Não muda | Não muda | "Caso para análise humana" | Frase do roteiro; a IA sai da conversa |
| Análise humana com transferência ligada | IA + regra `sinal:analise_humana` com "transferir" | Não muda | Não muda | Idem | Idem, e o atendimento vai para o departamento da regra (ou o padrão do agente) |

### 3.3 A equipe troca pelo painel

Na conversa, "Trocar etapa". O lead muda de etapa num comando só (se duas pessoas clicarem juntas, vale uma), fica o
histórico (origem "equipe") e a alteração no registro de quem fez. Entram na fila as mesmas automações da troca pela
IA: o **card vai para a coluna da etapa nova**, as etiquetas trocam e sai a nota. O próximo turno usa o agente novo,
com as boas-vindas dele.

### 3.4 A equipe move o card na Helena (novo)

Antes não existia (nem no n8n). Agora a Helena avisa o nosso servidor quando um card muda de coluna
(`PANEL_CARD_STEP_CHANGE`, incluído na assinatura do webhook) e o sistema:

1. acha o lead pelo card guardado (ou pelo atendimento/contato do card);
2. descobre a etapa daquela coluna pelas automações do agente (`etapa:closer` com a coluna "Comercial", por exemplo;
   a coluna do lead novo vale como SDR);
3. põe o lead nessa etapa, com histórico (origem "equipe_crm") e evento;
4. troca as etiquetas, deixa a nota e grava a marca das boas-vindas, **sem mover o card de novo** (ele já está lá);
5. a próxima mensagem do lead é respondida pelo agente daquela etapa.

**Proteções (laço e troca dupla):**

| Situação | O que acontece |
|---|---|
| A própria LawChat moveu o card e a Helena avisou | O lead já está na etapa da coluna: nada muda (`ja_estava`) |
| Aviso atrasado de um movimento nosso, com o lead já mais adiante | Reconhecido como eco (pedimos essa coluna nos últimos 10 min): o lead **não volta** e fica o evento `card_eco_ignorado` |
| A Helena repete o mesmo aviso | Entra uma vez só |
| Dois avisos ao mesmo tempo | Só um troca a etapa e põe as ações na fila |
| Coluna sem etapa ligada (ex.: "Arquivo") | Nada muda no agente (o espelho do card é atualizado) |
| Coluna usada por duas etapas | Nada muda (não dá para saber qual) |
| Card de outro painel, de outra conta ou sem lead | Ignorado |
| Lead em Contrato assinado ou encerrado | Não sai de lá pelo card |
| Escritório que não quer isso | `seguir_coluna_do_crm: false` no agente desliga |

O card movido pela equipe **não religa a IA**: se o lead estava pausado (atendente assumiu, análise humana), continua
pausado até a equipe devolver.

### 3.5 O "@" no nosso sistema

- O painel continua gravando o chip já expandido ("acionar tool `closer`" e o texto da frase), e o motor também entende
  o chip cru, para prompt colado, importado ou gravado sem a expansão:
  - `@Agente Closer` e `@Transferência: Closer` viram o destino "closer" da lista do `transferir_para`;
  - no texto que vai para a IA, `@Transferência: Closer` é trocado pela frase de entrada do Closer (a IA nunca vê o
    chip para copiá-lo);
  - um chip que **não** é agente do produto (`@Agente Financeiro`, `@Transferência: Jurídico`) não vira destino; a
    IA que pedir esse destino não troca o lead; e a equipe recebe um aviso de cadastro (`arroba_sem_destino`), uma vez
    por conversa;
  - se a IA escrever um chip para o lead ("@Agente Closer", "@Transferência"), a resposta é reprovada e refeita. Antes,
    o "@Transferência" com acento passava por essa trava.

---

## 4. Caso → resultado → teste que prova

Arquivo dos testes: `tests/test_e2e_troca_departamento.py` (TD) e `tests/test_e2e_helena.py` (E2E).

| # | Caso | Resultado esperado | Teste |
|---|---|---|---|
| a1 | IA leva o lead SDR → Closer → Contratos → Assinatura → Contrato assinado | Em cada passo: etapa no banco, card na coluna certa, etiqueta, nota e frase; um card só, cada coluna uma vez | TD `test_a_ia_leva_o_lead_do_sdr_ao_contrato_assinado` |
| a2 | IA desqualifica | Coluna e etiqueta de Desqualificado, nota, frase; o agente Desqualificado assume | TD `test_a_ia_desqualifica_e_o_agente_desqualificado_assume` |
| a3 | SDR → Closer e o próximo turno usa o prompt do Closer | Etapa, card, etiquetas e nota | E2E `test_sdr_qualifica_e_passa_para_o_closer` |
| a4 | Troca na primeira resposta | Recusada | E2E `test_troca_na_primeira_resposta_e_recusada` |
| a5 | Helena fora na resposta que troca | O lead fica no agente antigo, o card não move | E2E `test_troca_com_a_helena_fora_nao_muda_o_agente` |
| b1 | IA pede análise humana, transferência ligada | IA pausada, uma nota, atendimento transferido para o departamento da regra; sem departamento na regra, o padrão do agente | TD `test_b_analise_humana_transfere_para_o_departamento_configurado` |
| b2 | Análise humana sem transferência configurada | IA pausada e nota; nenhuma transferência | TD `test_b_analise_humana_sem_transferencia_configurada_so_pausa_e_avisa` |
| c1 | Equipe arrasta o card para o Comercial | Lead vai para Closer (origem equipe_crm), etiqueta e nota trocam, o card não é movido de novo, o próximo turno é do Closer com as boas-vindas | TD `test_c_equipe_move_o_card_e_a_ia_responde_como_o_agente_da_coluna` |
| c2 | Coluna sem etapa, outro painel, card sem lead, outra conta, lead com contrato assinado | Nada muda | TD `test_c_coluna_sem_etapa_card_de_outro_painel_e_lead_encerrado_nao_mudam_nada` |
| c3 | Escritório desligou a troca pelo card | Nada muda | TD `test_c_escritorio_pode_desligar_a_troca_pelo_card` |
| d1 | Equipe troca pelo painel | Card, etiqueta e nota na Helena; aviso de volta da Helena não muda nada; pedir de novo não refaz | TD `test_d_troca_pelo_painel_move_card_etiqueta_e_nota_na_helena` |
| d2 | Troca pelo painel e boas-vindas do agente novo | O agente novo se apresenta na 1ª resposta | E2E `test_equipe_troca_o_agente_pelo_painel_e_a_ia_segue_com_o_novo_prompt`, `test_troca_pela_equipe_faz_o_agente_novo_se_apresentar` |
| e1 | Chip `@Agente Closer` no roteiro | Vira o único destino; destino não citado é recusado; o chip não vaza | E2E `test_troca_pelo_arroba_agente_do_prompt` |
| e2 | Chip `@Transferência: Closer` cru | Vira destino, a IA recebe a frase no lugar do chip, a troca acontece e nada vaza | TD `test_e_chip_transferencia_cru_vira_destino_e_nunca_vaza` |
| e3 | Chip inválido `@Agente Financeiro` | Não vira destino, a troca pedida é recusada, aviso de cadastro uma vez, chip escrito ao lead é refeito | TD `test_e_arroba_invalido_e_barrado_e_avisado` |
| e4 | Leitura dos chips (unitário) | Destinos, chips inválidos, expansão e trava com acento | `tests/test_catalogo.py::test_chips_de_troca_do_painel_no_prompt` |
| f1 | Mesmo arraste avisado várias vezes, ao mesmo tempo | Uma troca, uma nota, uma etiqueta | TD `test_f_aviso_do_card_repetido_ou_simultaneo_troca_uma_vez_so` |
| f2 | Aviso atrasado do card que a LawChat moveu | O lead não volta; evento de eco | TD `test_f_aviso_atrasado_do_card_que_a_lawchat_moveu_nao_volta_o_lead` |
| f3 | Duas trocas simultâneas pelo painel | Vale uma; um movimento de card | TD `test_f_duas_trocas_simultaneas_pelo_painel_valem_uma_vez` |
| f4 | IA marca um destino e escreve a frase de outro (o TK-1773 do nosso lado) | Reprovada e refeita; um destino só por resposta | TD `test_f_uma_resposta_da_ia_so_pede_um_destino` |
| f5 | Webhook duplicado | Uma resposta só | E2E `test_webhook_duplicado_gera_uma_resposta_so` |

---

## 5. O que mudou nesta rodada (código)

- **Card movido na Helena troca o agente** (`app/troca_etapa.py`, chamado pelo webhook do escritório em
  `app/main.py`); `PANEL_CARD_STEP_CHANGE` entrou na lista de eventos assinados (`app/canal/helena_conta.py`). Nas
  contas já ligadas, a conferência da ativação passa a mostrar "será corrigida na ativação" e a assinatura ganha o
  evento novo na próxima ativação (ou onboarding). Até lá, arrastar o card não chega ao nosso servidor.
- **Troca pelo painel e troca pelo card usam a mesma função** (`trocar_pela_equipe`): a rota do painel ficou mais curta
  e faz o mesmo de antes.
- **Chip `@Transferência: X` cru** é entendido pelo motor e trocado pela frase; **chip inválido** gera aviso de
  cadastro (`app/cerebro/catalogo.py`, `app/cerebro/turno.py`).
- **Trava de texto interno sem acento:** "@Transferência" escrito pela IA não passava pela trava (ela procurava
  "@transferencia", sem acento).

---

## 6. O que ainda não existe (e proposta)

1. **"@" digitado pelo atendente no chat.** Não existe aqui nem no n8n. Cuidado: o que o atendente escreve no chat da
   Helena **vai para o lead** pelo WhatsApp; um "@closer" digitado ali seria enviado ao cliente. Proposta, em ordem:
   - **Já dá hoje:** arrastar o card na Helena (seção 3.4) é o "@" da equipe, sem digitar nada.
   - **Nota interna com comando:** o atendente escreve uma **nota** (não mensagem) começando com `@IA Closer`,
     `@IA Contratos` ou `@IA desligar`. O leitor do webhook já descarta mensagens do tipo `NOTE`, sinal de que as notas chegam (hoje são ignoradas). O
     sistema troca a etapa pelo mesmo caminho da seção 3.4 e responde com outra nota ("🤖 Agora quem atende é o
     Closer"). Falta: confirmar com uma conta real o formato da nota no webhook e quem a escreveu.
   - **Botão na Helena:** o mesmo endereço do botão "IA" (`/webhook/helena/{escritório}/ia`) com
     `{"acao": "etapa", "etapa": "closer"}`, para escritórios que preferem botão.
2. **Formato real do aviso de card movido.** A Helena não documenta o corpo do `PANEL_CARD_STEP_CHANGE`. O código
   aceita os formatos prováveis (card no `content` ou em `content.card`; coluna em `stepId`, `newStepId` ou `step.id`).
   **Antes de prometer ao cliente: arrastar um card numa conta de teste e conferir o aviso que chega.** Medir também o
   volume (a assinatura vale para a conta inteira).
3. **Análise humana não transfere por padrão.** Ela pausa a IA e deixa a nota; o atendimento só vai para um
   departamento se a regra `sinal:analise_humana` tiver "transferir" (e a função "Troca de departamento" estiver
   ligada). Proposta: incluir essa regra na sugestão do catálogo, com o departamento escolhido na ativação.
4. **Etiquetas de qualificação por IA ao ir para o Comercial** (Geral do n8n: "ERA CLT", "POSSUI DOCUMENTOS
   MÉDICOS"...). Não existem aqui; nossas etiquetas são só as da etapa. Se o escritório usa, dá para fazer pela fila
   com o extrator que já temos (os fatos já estão gravados, sem outra chamada de IA).
5. **Alerta no grupo do cliente** ("Lead qualificado", "Proposta aceita"): aqui é o "Avisos à equipe" por evento
   (`etapa:closer`, `etapa:contratos`), que o escritório liga na tela de avisos. Conferir com cada escritório que usava
   o grupo.
6. **Período de Graça sem coluna própria:** se ele usar a mesma coluna do SDR, arrastar o card para essa coluna não
   troca o agente (coluna de duas etapas). É de propósito.
7. **Janela do eco (10 minutos):** se a LawChat moveu o card para uma coluna e, nesses 10 minutos, a equipe trocar o
   lead pelo painel e depois arrastar o card de volta para aquela mesma coluna, o arraste é tomado como eco e ignorado
   (fica o evento `card_eco_ignorado`). Caso raro; a equipe pode trocar pelo painel.
8. **Card movido não religa a IA** de um lead pausado. Se o escritório quiser que arrastar para uma coluna devolva a
   conversa à IA, é uma opção nova.
