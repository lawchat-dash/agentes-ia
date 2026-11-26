# Ligar e desligar a IA

Este guia explica, sem termos técnicos, como tirar a IA de uma conversa e como devolver, em cada nível: uma conversa,
um produto (agente) ou o escritório inteiro. Também explica o que acontece sozinho quando um atendente entra na conversa.

Resumo rápido:

| Nível | Quem pode | Onde | O lead recebe algo? |
|---|---|---|---|
| Uma conversa | gestor e atendente | painel (Conversas), etiqueta ou botão na Helena | não, enquanto estiver desligada |
| Um produto (agente / número) | só gestor (e a equipe LawChat) | painel (Meus produtos / Agente) | não, nenhum lead daquele número |
| Escritório inteiro | só gestor (e a equipe LawChat) | painel (Configurações) | não, nenhum lead do escritório |
| Automático | ninguém aperta nada | o atendente fala na conversa | não, por um tempo (padrão 15 min) |

---

## 1. Uma conversa (um lead)

### Três jeitos, o mesmo resultado

1. **Painel, tela Conversas.** Abra a conversa. Em "A IA nesta conversa":
   - **Desativar IA** abre as opções **Por 30 minutos**, **Por 2 horas**, **Por 24 horas** e **Até eu religar**.
   - **Reativar IA** aparece quando a IA está desligada ou pausada.
   - **Encerrar** tira a conversa do atendimento (para voltar, use "Devolver para a IA").
2. **Helena, etiqueta.** Pôr a etiqueta **🤖 IA Desativada** no contato desliga a IA. Tirar a etiqueta religa.
3. **Helena, botão ou automação.** Um botão (ou automação) que chama o endereço
   `/webhook/helena/{escritório}/ia` com `acao: desligar` ou `acao: ligar`, o atendimento (`sessionId`) ou o telefone
   (`phone`) e, se quiser prazo, os minutos (`minutes`). O endereço usa o mesmo segredo do webhook do escritório.

Qualquer um dos três faz exatamente a mesma coisa:

**Ao desativar**
- a IA para de responder aquele lead (fica gravado o estado e, se houver prazo, até quando);
- os follow-ups que estavam agendados para ele são cancelados;
- a etiqueta **🤖 IA Desativada** vai para o contato na Helena (se veio da etiqueta, ela já está lá);
- uma nota aparece no chat da Helena com um código **DES-…** (ex.: `DES-3FA21C`), dizendo até quando;
- fica registrado no Histórico do painel quem desativou, por onde e quando.

**Ao reativar**
- a IA volta a responder **a partir da próxima mensagem do lead**;
- ela continua **da etapa em que o lead estava** (não recomeça a conversa) e **não repete as boas-vindas**;
- a etiqueta **🤖 IA Desativada** sai do contato;
- uma nota com código **ATV-…** aparece no chat;
- fica registrado no Histórico quem reativou.

### Desligar por um tempo (30 min, 2 h, 24 h)

- Quando o prazo acaba, **a IA volta sozinha**, sem mandar nenhuma mensagem para o lead. A etiqueta sai e fica uma
  nota "IA religada sozinha (ATV-…)".
- Se o lead escreveu enquanto a IA estava desligada e ninguém da equipe respondeu, a IA responde essa mensagem
  assim que o prazo acaba.
- Se a equipe já respondeu o lead depois da última mensagem dele, a IA fica calada (não responde por cima).
- Se o atendente falar na conversa durante o prazo, o prazo escolhido continua valendo (a fala do atendente não
  encurta uma desativação de 2 h ou 24 h).
- Reativar antes do prazo também vale: a IA volta na hora (e responde o que estiver esperando).

### O que aparece no painel

Na lista e na conversa aberta, cada conversa mostra o estado da IA:

| O painel mostra | Quer dizer |
|---|---|
| **IA ligada** | a IA responde normalmente |
| **IA desligada até 14:30** | desligada pela equipe com prazo; volta sozinha nesse horário |
| **IA desligada pela equipe** | desligada "até eu religar"; só volta quando alguém reativar |
| **Pausada porque o atendente assumiu** | pausa automática (veja o item 4), com o horário em que volta |
| **Agente pausado** | o produto inteiro está pausado (item 2) |
| **IA desligada no escritório** | o escritório inteiro está desligado (item 3) |
| **Encerrada** | conversa encerrada |

---

## 2. Um produto (agente / número de WhatsApp)

- **Onde:** no painel, em Meus produtos (ou na tela do agente), botão de pausar/ativar.
- **Quem:** só o gestor do escritório (e a equipe LawChat). O atendente não consegue.
- **O que acontece:** nenhum lead daquele número recebe resposta nem follow-up. Cada mensagem que chega fica gravada
  e a equipe recebe uma nota no chat: "O agente de IA deste canal está pausado". Na tela Conversas aparece o aviso
  "Agente pausado".
- **Ao religar:** a IA volta a responder só as mensagens novas. O que chegou durante a pausa **não dispara de uma vez**
  (sem rajada), e os follow-ups que venceram durante a pausa foram cancelados, não guardados.
- Fica registrado no Histórico (pausou / ativou) com quem fez.

## 3. O escritório inteiro

- **Onde:** no painel, em Configurações, chave "IA ligada no escritório".
- **Quem:** só o gestor (e a equipe LawChat).
- **O que acontece:** nenhum lead do escritório recebe resposta nem follow-up. Cada mensagem fica gravada e a equipe
  recebe a nota "A IA está desligada neste escritório". A tela Conversas mostra "IA desligada no escritório".
- **Ao religar:** igual ao produto, sem rajada: só as mensagens novas são respondidas.
- Fica registrado no Histórico (desligou_ia / ligou_ia) com quem fez.

## 4. Automático: o atendente assumiu

- Quando alguém da equipe escreve para o lead pela Helena, a IA sai da conversa por um tempo (padrão 15 minutos,
  ajustável no agente). Cada nova fala do atendente recomeça a contagem.
- Os follow-ups do lead são cancelados.
- O painel mostra "Pausada porque o atendente assumiu (volta 14:45)".
- Quando o tempo acaba, a IA volta sozinha, sem mandar mensagem, e responde a próxima mensagem do lead.
- Para devolver antes, use **Reativar IA** no painel ou o botão "ligar" da Helena. Mexer em outras etiquetas não
  religa uma pausa do atendente.
- Se o agente estiver configurado como "pausa sem volta", só a equipe religa.

---

## Perguntas comuns

**Por que tirei a etiqueta na Helena logo depois de desligar pelo painel e nada mudou?**
Por 3 minutos depois de a LawChat pôr ou tirar a etiqueta, o evento da Helena com o mesmo resultado é tratado como
"eco" da própria LawChat e ignorado; é isso que impede o liga-desliga sem fim. Se você repetir exatamente a mesma
mudança que a LawChat acabou de fazer, espere 3 minutos ou use o painel.

**A IA manda alguma mensagem ao lead quando volta?**
Não. Ela só responde quando o lead escreve (ou responde a mensagem que ficou esperando durante a pausa com prazo).

**Desliguei uma conversa e o lead tem dois números/produtos.**
O painel desliga só aquela conversa. A etiqueta e o botão da Helena valem para o contato (todas as conversas abertas
dele no escritório).

---

## Tabela de casos (caso → resultado → teste)

Os testes ficam em `tests/test_ligar_desligar_ia.py` (ponta a ponta com banco local e Helena falsa), salvo indicação.

| Caso | Resultado | Teste |
|---|---|---|
| Atendente desativa "até eu religar" pelo painel | IA calada, follow-up cancelado, etiqueta posta, nota DES, histórico com o atendente | `test_painel_desativa_e_reativa_com_o_mesmo_efeito_da_etiqueta_e_sem_boas_vindas` |
| Reativar pelo painel | etiqueta tirada, nota ATV, histórico; IA segue da etapa (closer) sem boas-vindas | mesmo teste acima |
| Eco da etiqueta que a LawChat pôs/tirou | nada muda, nenhuma nota nova | mesmo teste acima |
| Desativar e reativar rápido, Helena manda os ecos (até repetidos) | IA fica ligada, sem laço, uma alteração de cada | `test_desativar_e_reativar_rapido_nao_entra_em_laco_com_os_ecos_da_etiqueta` |
| Equipe põe / tira a etiqueta na Helena | desliga (follow-up cancelado, nota DES, LawChat não mexe na etiqueta) / religa (nota ATV) | `test_etiqueta_posta_pela_equipe_na_helena_desliga_e_tirada_religa` e `tests/test_e2e_helena.py::test_etiqueta_ia_desativada_desliga_e_tirar_religa` |
| Botão da Helena desliga por 30 min; lead escreve no meio | nada sai; mensagem guardada; no fim do prazo a IA volta sozinha e responde | `test_botao_com_prazo_guarda_a_mensagem_e_responde_quando_o_prazo_vence` |
| Prazo de 2 h acaba sem mensagem esperando | IA volta sozinha, sem mandar nada; nota "religada sozinha" | `test_prazo_vence_sem_mensagem_esperando_e_a_ia_nao_manda_nada` |
| Prazo acaba, mas a equipe já respondeu o lead | IA fica calada (turno "equipe_respondeu") | `test_prazo_vence_mas_a_equipe_ja_respondeu_e_a_ia_fica_calada` |
| Atendente fala durante desativação de 24 h | o prazo de 24 h continua | `test_atendente_falando_nao_encurta_a_desativacao_de_24_horas` |
| Atendente assume a conversa | "pausada porque o atendente assumiu", com volta; Reativar tira na hora | `test_atendente_assumiu_aparece_como_pausa_automatica` e `tests/test_e2e_helena.py::test_atendente_assume_ia_pausa_e_botao_religa` |
| Produto pausado / escritório desligado | lead não recebe nada, nota para a equipe, follow-up vencido cancelado, painel mostra; ao religar, sem rajada | `test_produto_pausado_e_escritorio_desligado_lead_nao_recebe_nada_e_sem_rajada_ao_religar` |
| Permissões | atendente: conversa sim, produto/escritório não (403); gestor: tudo; sem login: 401 | `test_quem_pode_desligar_e_religar` |
| Botões e estados da tela | "IA ligada", "IA desligada até…", "IA desligada pela equipe", "Pausada porque o atendente assumiu"; 30 min, 2 h, 24 h, até religar | `test_tela_conversas_tem_os_estados_e_as_opcoes_de_desativar` e `tests/test_conversas_tela.py` |
| Etiqueta repetida, botão sem efeito, conversa desconhecida | sem repetir nota; nota "já estava…"; nota "conversa não encontrada" | `tests/test_ia_controle.py` |

---

## Para quem mexe no código

- Tudo passa por `app/ia_controle.py`: `mudar_ia` (painel, etiqueta e botão) e `religar_vencidas` (prazo que acabou).
- Painel: `POST /api/conversas/{id_lead}/ia` com `{acao: "desativar", minutos}` ou `{acao: "reativar"}`
  (`pausar` e `devolver` continuam aceitos como nomes antigos).
- O prazo é conferido a cada minuto (`Atendimento.retomar_pendentes`) e também quando chega mensagem do lead.
- Estado no banco: `agentesia_leads.estado = 'pausado'`, `motivo_estado = 'desativada_pela_equipe'` e `pausado_ate`
  (vazio = até religar). Pausa do atendente: `motivo_estado = 'humano_assumiu'`.
