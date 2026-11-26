# Follow-up

Quando o lead para de responder, a IA manda um lembrete curto, no tom do agente, no tempo de cada tentativa. Ela para
sozinha quando o lead responde ou alguém da equipe assume.

**Regra nova (25/11/2026, decisão do dono): o follow-up vem LIGADO ao ativar um produto.** Antes, cada escritório
precisava lembrar de ligar na aba Follow-up do agente, e muitos esqueciam. Agora quem não quiser desliga
(opt-out, em vez de opt-in).

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

Se o produto não definiu cadência, vale a do sistema: 1 h, 5 h, 24 h, 72 h, 7, 15 e 30 dias. Se nenhuma etapa foi
marcada, valem todas as etapas de conversa. A desistência automática (encerrar o lead depois da última tentativa)
vem desligada.

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
| Cadência, envio, cancelamento e desistência | `tests/test_followup.py` |
| Horário comercial empurra para a próxima abertura | `tests/test_followup.py::test_horario_comercial_empurra_para_a_proxima_abertura` |

Os testes com banco precisam do banco local: `node db/testes/servidor_local.mjs 55741` e
`AGENTESIA_TESTE_PG_URL=postgresql://postgres:postgres@127.0.0.1:55741/postgres`.

## 6. Arquivos

- `app/followup/padrao.py`: padrão do produto, resumo da cadência, situação, ligar com o padrão, visão do admin.
- `app/followup/regras.py`: configuração, validação e horário (desqualificado e contrato assinado fora sempre).
- `app/followup/servico.py`: agenda e disparador (os motivos da seção 4).
- `app/gestao/produtos.py`: a ativação copia o padrão (`_com_followup_padrao`); as linhas trazem `followup_situacao`.
- `app/gestao/rotas_followup.py`: prévia da etapa, “Ligar com o padrão” e as rotas do admin.
- `app/gestao/rotas.py`: `/api/inicio` traz `followup_desligado`.
- `scripts/ligar_followup_padrao.py`: ligar os já ativos.
- Painel: `components/agent/ProductConfigurator.tsx` (etapa Follow-up), `components/followup/AvisoFollowupDesligado.tsx`,
  `pages/MeusProdutos.tsx`, `telas/Inicio.tsx`, `telas/AdminFollowup.tsx`.
