# Follow-up

Quando o lead para de responder, a IA manda um lembrete curto, no tom do agente, no tempo de cada tentativa. Ela para
sozinha quando o lead responde ou alguém da equipe assume.

**Regra nova (25/11/2026, decisão do dono): o follow-up vem LIGADO ao ativar um produto.** Antes, cada escritório
precisava lembrar de ligar na aba Follow-up do agente, e muitos esqueciam. Agora quem não quiser desliga
(opt-out, em vez de opt-in).

**Regras da OAB e da Meta (26/11/2026, aprendizado 5 da pesquisa).** O Provimento OAB 205/2021 veda captação e mala
direta para quem não autorizou, e a Meta derruba a nota do número que insiste. Por isso a cadência padrão nova tem no
máximo 4 toques, quem nunca respondeu recebe no máximo 2, o penúltimo toque oferece parar e o pedido para parar
cancela tudo (seção 2.1). O interruptor continua ligado por padrão; a mudança está na cadência.

## 1. Como funciona

1. Cada vez que a IA responde, o follow-up pendente do lead é trocado pela 1ª tentativa, contada a partir dessa
   resposta (`app/followup/servico.py`, `agendar`).
2. Um laço roda a cada minuto no servidor da IA (`Disparador`). Ele pega até 5 tentativas vencidas, confere tudo de
   novo na hora (seção 4), escreve a mensagem (a IA lê a conversa e segue o prompt do follow-up) e envia pela Helena.
3. Depois de enviar, agenda a tentativa seguinte. Cada tempo conta a partir da última resposta da IA, não da
   tentativa anterior.
4. Se o lead responder, a IA responde e a cadência recomeça do início.

Onde fica a configuração: `agentesia_agentes.config.followup` (ligado, tentativas, horário, etapas, prompt, instrução
por etapa, modelo aprovado do número oficial). O formato está no topo de `app/followup/regras.py`.

## 2. A cadência padrão

A cadência vem do **produto da biblioteca** (admin › Produtos › aba Follow-up), no campo `padrao_followup`:

- `cadence`: os tempos, por exemplo 10 min, 1 h, 24 h, 72 h. Aceita `"10m"`, `"1h"`, `"2d"`, `"1sem"` ou números
  (horas);
- `agentes`: um prompt por etapa do CRM (SDR, Closer, Contrato, Assinatura) e se a etapa recebe follow-up
  (`habilitado_padrao`).

Na ativação, isso vira a configuração do agente (`app/followup/padrao.py`, `config_do_produto`):

| No produto (CRM) | No agente |
|---|---|
| sdr | sdr e periododegraca (o Weaver também espelhava o SDR no Período de Graça) |
| closer | closer |
| contrato | contratos |
| assinatura | assinatura |
| prompt da etapa | instrução extra da etapa (`por_etapa`) |
| `habilitado_padrao: false` | a etapa fica fora da lista |

Se o produto não definiu cadência, vale a do sistema: **1 h, 24 h, 72 h e 7 dias** (`regras.CADENCIA_PADRAO`). Se o
produto definiu mais de 4 tempos, só os 4 primeiros entram. Se nenhuma etapa foi marcada, valem todas as etapas de
conversa. A desistência automática (encerrar o lead depois da última tentativa) vem desligada.

### 2.1 Regras da OAB e da Meta

Quem ativa (ou clica em **Ligar com o padrão**) a partir de 26/11/2026 recebe, junto da cadência, o bloco `limites`:

```
"limites": {"max_toques_sem_resposta": 2, "oferecer_parar": true, "lead_parado_apos": 3}
```

| Regra | Como funciona | Onde |
|---|---|---|
| No máximo 4 toques | A cadência padrão e a copiada do produto param no 4º tempo | `regras.CADENCIA_PADRAO`, `padrao.config_do_produto` |
| Quem nunca respondeu à IA: no máximo 2 | "Nunca respondeu" = nenhuma mensagem do lead depois da primeira mensagem da IA. O 3º toque não é agendado; se já estava na fila, é cancelado (`limite_sem_resposta`) | `Config.total_de_toques`, `servico.respondeu_a_ia` |
| O penúltimo toque oferece parar | No fim da última mensagem do toque entra “Se preferir que eu não mande mais mensagens, é só me avisar.” (se a IA já não disse algo parecido). Penúltimo do total deste lead: o 3º de 4 ou o 1º de 2. Não vale para o modelo aprovado da API oficial (texto fixo da Meta) | `Config.leva_opcao_de_parar`, `regras.com_opcao_de_parar` |
| Pedido para parar | “pare”, “para de me mandar”, “não quero mais”, “sair”, “quero sair”, “remover”, “me tira da lista”, “descadastrar”... na **última mensagem do lead**: o envio é cancelado com `lead_pediu_para_parar` e fica um evento `followup_lead_pediu_para_parar`. Na próxima resposta da IA o agendar não agenda e grava uma linha cancelada com o mesmo motivo (aparece em “Recentes” da aba). Se o lead volta a conversar, a cadência volta. Vale para **todas** as configs | `regras.pediu_para_parar`, `servico.agendar`, `Disparador._por_que_nao` |

**Quem já tinha cadência configurada não muda.** Config sem `limites` (todas as gravadas antes de 26/11) segue com os
seus passos, sem limite para quem nunca respondeu e sem a frase. Só o pedido para parar e o lead parado (seção 2.2)
valem para todos. Para trazer um agente antigo para as regras novas: **Ligar com o padrão** (ou o script).

Atenção para a tela de edição: `regras.validar(dados, anterior=...)` guarda os `limites` da config anterior quando a
tela não manda o campo. A rota `PUT /api/agentes/{id}/followup` (`app/gestao/rotas.py`, `salvar_followup`) ainda chama
`regras.validar(dados)` sem o `anterior`, e `_followup_para_tela` não devolve `limites`. Enquanto isso não mudar
(frente da gestão), salvar a aba Follow-up apaga os limites desse agente. A troca é de uma linha:
`regras.validar(dados, anterior=(agente.get("config") or {}).get("followup"))`.

### 2.2 Lead parado vira tarefa da equipe

24 h depois do 3º toque (`lead_parado_apos`, padrão 3; 0 desliga) sem resposta do lead e sem a equipe falar, o lead
vira tarefa da equipe, uma vez por ciclo de follow-up (`servico.varrer_parados`, a cada minuto junto com o disparador):

- nota **“Lead parado: retomar contato”** no atendimento (pela fila de ações; se a automação `lead_parado` do agente
  tiver nota própria, sai a dela no lugar);
- o que o escritório configurou no gatilho **Lead parado** das automações: etiqueta, coluna do CRM;
- o aviso por WhatsApp do evento `lead_parado` em **Avisos à equipe** (com a função de avisos ligada);
- o evento `lead_parado` (info) na central de eventos.

Os toques automáticos seguem a cadência (o 4º sai no 7º dia). Não entra quem está pausado, encerrado,
desqualificado ou com contrato assinado.

## 3. Como ligar e desligar

| Onde | O que faz |
|---|---|
| Ativação do produto, etapa **Follow-up** (passo 5 de 6) | Mostra a cadência padrão resumida e o interruptor já ligado, com o motivo para deixar ligado. Desligar ali = o agente nasce com a cadência pronta, mas desligada |
| Agente › aba **Follow-up** | Liga, desliga e ajusta tempos, prompt, horário e etapas. Desligar cancela os envios pendentes |
| **Início**, **Meus produtos** e a **tela do produto** | Produto ativo com follow-up desligado mostra o aviso “Follow-up desligado — leads que param de responder não recebem lembrete” e o botão **Ligar com o padrão** |
| Admin › LawChat › **Follow-up** | Lista todos os escritórios e produtos, ligados e desligados. Liga um a um, os marcados ou todos os ativos desligados (sempre com confirmação) |
| `scripts/ligar_followup_padrao.py` | O mesmo, pela linha de comando, para os produtos ativados antes da regra nova |

**Ligar com o padrão** grava a cadência e os prompts padrão do produto da biblioteca. Guarda o horário, o modelo de IA e
o modelo aprovado que o agente já tinha. Toda ligação fica em `agentesia_alteracoes`, com o antes e o depois, e a
origem (painel, admin ou script).

Salvar a edição do produto (sincronizar) **não** liga nem desliga o follow-up: quem manda é a aba Follow-up. Se o
agente ainda não tinha follow-up (produto ativado antes da regra), a sincronização copia a cadência padrão
**desligada** e o aviso aparece para o cliente decidir.

### Produtos que já estavam ativos

Nada liga sozinho em produção. O dono decide:

```
python scripts/ligar_followup_padrao.py                                   # só lista
python scripts/ligar_followup_padrao.py --escritorio <uuid>               # lista um escritório
python scripts/ligar_followup_padrao.py --produto <id_ativado> --aplicar  # liga um (pode repetir --produto)
python scripts/ligar_followup_padrao.py --todos-desligados --aplicar      # liga todos os ATIVOS desligados
```

Sem `--aplicar` o script só mostra o que faria. A mesma ação está na tela do admin. Rotas:
`GET /api/admin/followup` e `POST /api/admin/followup/ligar` com `{"ids": [...]}` ou `{"todos_desligados": true}`.
`"simular": true` só mostra quem seria ligado; sem lista e sem `todos_desligados`, a rota recusa.

Ligar não manda nada na hora: o follow-up de cada lead começa a contar a partir da próxima resposta da IA.

## 4. Quando ele não manda

O disparador confere tudo na hora do envio, e o envio é cancelado com o motivo gravado em `agentesia_followups.motivo`:

| Caso | Motivo |
|---|---|
| Follow-up desligado | `followup_desligado` |
| IA desligada no escritório (interruptor de emergência) ou escritório inativo | `ia_desligada_no_escritorio` |
| Agente (produto) pausado | `agente_pausado` |
| Atendente assumiu ou a IA foi desligada para o lead (etiqueta, botão, painel) | `lead_pausado` |
| Lead encerrado (pediu para parar, engano, desistência) | `lead_encerrado` |
| A última mensagem do lead pede para parar (“pare”, “não quero mais”, “sair”, “remover”...) | `lead_pediu_para_parar` |
| Nunca respondeu à IA e já recebeu o máximo (`limites.max_toques_sem_resposta`) | `limite_sem_resposta` |
| Alguém da equipe falou com o lead depois da última resposta da IA | `equipe_falou` |
| O lead respondeu | `lead_respondeu` |
| Lead desqualificado (nunca recebe, mesmo se a etapa estiver na lista) | `lead_desqualificado` |
| Contrato assinado (etapa final ou contrato `assinado` na ZapSign) | `contrato_assinado` |
| Etapa sem follow-up | `etapa_sem_followup` |
| Agente em modo teste e número fora dos de teste | `modo_teste` |

Outros casos adiam ou trocam a mensagem, sem cancelar:

- **Horário:** fora do horário (padrão segunda a sábado, 8h às 20h, Brasília) a tentativa vai para a próxima
  abertura, com alguns minutos de diferença entre leads (`fora_do_horario`).
- **Intervalo mínimo:** nunca menos de 30 min depois da última mensagem enviada ao lead (`intervalo_minimo`).
- **Janela de 24 h do número oficial:** depois de 24 h sem mensagem do lead, o WhatsApp só aceita modelo aprovado.
  Com o modelo escolhido na aba Follow-up, sai o modelo. Sem ele, a tentativa falha
  (`janela_fechada_sem_modelo`) e a equipe recebe um aviso. A ativação liga o follow-up também no número oficial: as
  tentativas dentro das 24 h saem normalmente, e a tela do admin mostra “falta modelo aprovado”.
- **Saldo:** com o limite de consumo do mês estourado, a tentativa sai com um texto simples de reserva, sem gastar
  IA. A frente de cobrança está criando o “pode gastar”, que ainda não existe no código. Quando existir, o ponto a
  trocar é `Disparador._consumo_estourado` em `app/followup/servico.py`.

## 5. Caso → teste

| Caso | Teste |
|---|---|
| Lê a cadência do produto em qualquer formato (`10m`, `1h`, `3d`, horas) | `tests/test_followup_padrao.py::test_le_a_cadencia_do_produto_em_qualquer_formato` |
| Etapas do CRM → etapas do agente; prompts por etapa; produto sem padrão | `tests/test_followup_padrao.py::test_config_do_produto_mapeia_etapas_e_prompts` |
| Desqualificado e contrato assinado nunca recebem; passo de 10 min aceito | `tests/test_followup_padrao.py::test_desqualificado_e_contrato_assinado_nunca_recebem` |
| Ativação liga com o padrão; desligar e religar; aviso só quando desligado; sincronizar não muda; opt-out na ativação; produto pausado sem aviso; outro escritório não liga | `tests/test_followup_padrao.py::test_ativacao_liga_o_followup_com_o_padrao_desligar_religar_e_aviso` |
| Admin vê todos; simulação; um a um; lote dos desligados; registro em `agentesia_alteracoes` | `tests/test_followup_padrao.py::test_admin_ve_todos_e_liga_em_lote_com_registro` |
| Script: só lista sem `--aplicar`, liga com `--aplicar` | `tests/test_followup_padrao.py::test_script_so_lista_sem_aplicar_e_liga_com_aplicar` |
| Não manda: desqualificado, contrato assinado, IA desligada, agente pausado, atendente assumiu, equipe falou, lead respondeu, follow-up desligado | `tests/test_followup_padrao.py::test_nao_envia_para_desqualificado_contrato_assinado_ia_desligada_e_atendente` |
| Horário, janela de 24 h do número oficial, saldo estourado | `tests/test_followup_padrao.py::test_respeita_horario_janela_oficial_e_saldo` |
| Cadência padrão nova (4 toques), produto com mais de 4 tempos, `limites` | `tests/test_followup_oab.py::test_cadencia_padrao_nova_tem_4_toques_e_limites` |
| Config antiga (sem `limites`) não muda | `tests/test_followup_oab.py::test_quem_ja_tem_cadencia_configurada_nao_muda`, `::test_config_antiga_sem_limites_segue_igual` |
| Nunca respondeu: 2 toques, o 1º oferece parar; o 3º é cancelado | `tests/test_followup_oab.py::test_nunca_respondeu_recebe_2_toques_e_o_1o_oferece_parar` |
| Respondeu: 4 toques, o 3º oferece parar | `tests/test_followup_oab.py::test_quem_respondeu_recebe_4_toques_e_o_3o_oferece_parar` |
| Pedido para parar: frases reconhecidas e não confundidas; cancela e marca | `tests/test_followup_oab.py::test_reconhece_pedido_para_parar`, `::test_nao_confunde_com_pedido_para_parar`, `::test_pedido_para_parar_cancela_e_marca` |
| Lead parado: nota, aviso, etiqueta e evento, uma vez; não entra quem respondeu ou desligou | `tests/test_followup_oab.py::test_acoes_do_lead_parado`, `::test_lead_parado_vira_tarefa_da_equipe_uma_vez` |
| Cadência, envio, cancelamento e desistência | `tests/test_followup.py` |
| Horário comercial empurra para a próxima abertura | `tests/test_followup.py::test_horario_comercial_empurra_para_a_proxima_abertura` |

Os testes com banco precisam do banco local: `node db/testes/servidor_local.mjs 55741` e
`AGENTESIA_TESTE_PG_URL=postgresql://postgres:postgres@127.0.0.1:55741/postgres`.

### 5.1 Nota do lead (fica junto do follow-up)

`app/cerebro/temperatura.py` calcula a nota de 0 a 10 do lead (frio, morno, quente) com os motivos, sem IA. Ela roda
pelo gancho `automacoes.depois_do_turno`, chamado pelo `agendar` deste módulo (o pipeline chama o `agendar` depois de
cada resposta da IA). Fica em `agentesia_lead_fatos`, chave `_temperatura`. Na primeira vez que chega a 7 sai o evento
`lead_quente` e o aviso à equipe (nome, benefício, nota e motivos; nunca CPF). Testes: `tests/test_temperatura.py`.

## 6. Arquivos

- `app/followup/padrao.py`: padrão do produto, resumo da cadência, situação, ligar com o padrão, visão do admin.
- `app/followup/regras.py`: configuração, validação e horário (desqualificado e contrato assinado fora sempre),
  `limites`, a frase de parar e `pediu_para_parar`.
- `app/followup/servico.py`: agenda e disparador (os motivos da seção 4), pedido para parar, lead parado
  (`varrer_parados`) e o gancho da nota do lead no `agendar`.
- `app/automacoes.py`: gatilhos `lead_parado` e `lead_quente`, `acoes_do_lead_parado`, `depois_do_turno`.
- `app/notificacoes.py`: nomes dos eventos `lead_parado` e `lead_quente`, marcadores `{{beneficio}}`, `{{nota}}` e
  `{{motivos}}`, `texto_lead_quente`.
- `app/cerebro/temperatura.py`: a nota do lead.
- `app/gestao/produtos.py`: a ativação copia o padrão (`_com_followup_padrao`); as linhas trazem `followup_situacao`.
- `app/gestao/rotas_followup.py`: prévia da etapa, “Ligar com o padrão” e as rotas do admin.
- `app/gestao/rotas.py`: `/api/inicio` traz `followup_desligado`.
- `scripts/ligar_followup_padrao.py`: ligar os já ativos.
- Painel: `components/agent/ProductConfigurator.tsx` (etapa Follow-up), `components/followup/AvisoFollowupDesligado.tsx`,
  `pages/MeusProdutos.tsx`, `telas/Inicio.tsx`, `telas/AdminFollowup.tsx`.
