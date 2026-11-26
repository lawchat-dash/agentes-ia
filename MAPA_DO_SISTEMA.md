# Mapa do sistema

16/11/2026. Inventário de tudo o que o sistema em código precisa ter, para conferir antes de começar. Detalhes em [DESENHO.md](DESENHO.md) e [ESTRUTURA.md](ESTRUTURA.md).

> **Decisão de 22/11/2026 — sistema novo, do zero.** Onde este mapa diz "Reaproveita" uma tabela do Weaver ou da plataforma (`sistemaia_*`), leia "faz do zero, com tabela própria `agentesia_*`" ([db/TABELAS.md](db/TABELAS.md)). Modo sombra, roteamento por agente entre n8n e cérebro, importação de leads antigos e as pontes com o "Webhook Front" saem do escopo. O que vale das seções 10 e 11 são as regras e os problemas aprendidos nos fluxos, não as tabelas deles.

Legenda da coluna "Situação":
- **Desenhado**: já está no desenho.
- **Reaproveita**: já existe no banco ou na plataforma e será usado como está.
- **Falta decidir**: precisa de decisão antes de construir.
- **Novo**: não tinha sido discutido; acrescentado neste mapa.

## 1. Atendimento (o que o lead vê)

| Módulo | O que faz | Situação |
|---|---|---|
| Recepção do webhook | Recebe da Helena, confere origem, descarta duplicata, responde na hora | Desenhado |
| Classificação do evento | Lead, humano, eco da IA, outra integração, rastreio, status | Desenhado |
| Cadastro automático | Encontra ou cria contato, lead, conversa; card e etiqueta no CRM | Desenhado |
| Mídia | Transcrição de áudio (usa a da Helena quando vier), imagem, PDF, Word | Desenhado |
| Buffer | Junta mensagens picadas, ordem pelo horário do WhatsApp, uma resposta por vez | Desenhado |
| Origem e triagem | Classificação do anúncio com cache; triagem conversando quando não há origem | Desenhado |
| Cérebro | Extrator, funções de decisão, agente da etapa, travas | Desenhado |
| Produtos | Auxílio Acidente primeiro; BPC e outros como configuração | Desenhado; funil do BPC falta desenhar |
| Saída | Formatador, divisão, "digitando", checagem de mensagem nova antes de enviar | Desenhado |
| Recepção fora do horário | Apresentação e pergunta 24 horas; vídeo inicial só em horário comercial | Desenhado |
| Pausa por humano | Humano fala, IA pausa, volta sozinha depois do tempo configurado | Desenhado |
| Mensagens fixas | Abertura, segurança, fora da área, encerramento por motivo, pós-assinatura | Desenhado |
| Identidade do lead | O lead é achado pelo número dentro do canal, com ou sem o nono dígito, e pelo contato da Helena quando o número vem escondido. Mensagem do atendente **nunca** muda o telefone: a troca automática antiga era defeito (5.757 trocas em 7 dias) | Reaproveita a regra do n8n refeito |
| Mídia enviada pela equipe | Áudio e imagem que o humano manda também são transcritos para o histórico, para a IA entender a conversa quando voltar | **Novo** (o fluxo "Mensagem Enviada" já faz) |
| Documentos do lead | Laudo, CNIS, autos: o texto vira fatos com trecho, nunca decisão direta. Hoje um auditor separado decide desqualificação com "na dúvida, desqualifique"; no sistema novo quem decide é a função de qualificação | **Novo**: resumo de autos como apoio à equipe |
| Bloqueio de lead | Lead suspeito ou que pede bloqueio: etiqueta, cancela lembretes, IA nunca mais responde | Desenhado (estado terminal); etiqueta de bloqueio **Novo** |

## 2. Automação (o que roda sozinho)

| Módulo | O que faz | Situação |
|---|---|---|
| Follow-up | Cadência por etapa, inclusive para quem nunca respondeu; reagenda "amanhã"; templates no canal oficial após 24h | Reaproveita as tabelas de cadência; regras novas desenhadas |
| Reativação da IA | Religa após a pausa (hoje: agendamento no banco + fila `reativacao_fila`) | Reaproveita; trocar o agendamento por lead pelo agendador do sistema |
| Geração do contrato | Dois provedores por escritório: ZapSign (modelo) e Tramitação Inteligente (cliente por CPF, documentos, envelope); variante com menor de idade e representante; envio do contato do escritório | Desenhado; regras de cada provedor vêm do fluxo "Contrato" |
| Contrato assinado | Recebe o aviso do ZapSign, move etapa, mensagem final, desliga a IA | Desenhado |
| Conferência de assinatura | Lead diz "assinei": o código consulta o provedor. Hoje só olha o primeiro signatário, e se estiver assinado sem o aviso ter chegado o fluxo para com erro. No novo: confere todos os signatários e, se assinado, processa como contrato assinado. Uma varredura periódica pega avisos perdidos | **Novo** |
| Resumo pós-contrato | Avaliação da conversa que fechou contrato (hoje: agente "Resumo do Contrato") | Desenhado (auditor) |
| Avisos à equipe | Dez tipos, com auditor antes de enviar | Reaproveita `sistemaia_notificacoes` |
| Novas tentativas | Ações que falharam (Helena, ZapSign) | Desenhado |
| Reprocessar um atendimento | Botão dentro do painel da Helena: só reprocessa se a última mensagem for do lead; reaproveita o turno gravado em vez de montar um webhook falso (hoje: fluxo "Re-Execução") | **Novo** |
| Status de entrega do follow-up | Depois de enviar template, confere se foi entregue e grava o erro (hoje: espera 30 segundos e consulta) | Reaproveita `followup_events`; **Novo** no código |
| Importação de leads antigos | Trazer contatos e conversas da Helena para o banco (hoje: fluxo "Backfill") | **Novo**: manter como script de manutenção |
| Lote de mensagens da equipe | Disparos manuais da equipe ("tentamos te ligar") não podem confundir a IA | **Novo**: tratados como "outra integração" e gravados no histórico |

## 3. Plataforma e provisionamento

O app da plataforma (`sistemaia_*`) cria e altera escritórios, produtos, notificações e cadências. Hoje isso chega ao bot pelo fluxo "99 - Webhook Front" e por funções no banco.

| Evento do app | Hoje | No sistema novo | Situação |
|---|---|---|---|
| Produto criado, atualizado, pausado, excluído | Webhook Front + `sistemaia_sincronizar_produto_no_bot` | O cérebro lê a configuração direto da plataforma; mudança vale no próximo turno, sem compilar prompt | **Falta decidir**: manter as funções do banco para o n8n durante a migração |
| Ativar IA, criar CRM, etiquetas, webhook | Webhook Front | Mesmo comportamento, em código | Falta decidir a ordem |
| Notificação e cadência configuradas | Webhook Front | Lidas direto das tabelas | Reaproveita |
| Canal de WhatsApp pedido, sincronizar contas | Webhook Front | Mesmo comportamento, em código | Falta decidir a ordem |
| Pagamento e recarga | Webhook Front + Asaas | Fica como está; o cérebro só lê o saldo | Reaproveita |
| Publicação de configuração do cérebro | Não existe | Rascunho → testes → publicar → voltar versão | **Novo**: tela no app ou no Laboratório |

## 4. Cobrança e saldo

| Módulo | O que faz | Situação |
|---|---|---|
| Registro de consumo | Toda chamada de IA, transcrição e imagem em `consumo_tokens` | Desenhado |
| Cobrança | `sistemaia_processar_consumo`, markup, cotação, saldo | Reaproveita |
| **Corte por saldo** | Conta sem saldo (`sistemaia_saldos.pausado_por_saldo`) não pode ser atendida pela IA | **Novo**: regra de entrada; mensagem fixa ou silêncio, e aviso à equipe |
| Limites diário e mensal | `limite_diario_brl`, `limite_mensal_brl` | **Novo**: mesma regra de entrada |
| Chave de IA do escritório | Alguns fluxos usam a chave OpenAI gravada no cadastro do escritório (transcrição, documentos). Precisa definir: chave da LawChat para todos, ou chave própria e consumo não cobrado | **Falta decidir** |

## 5. Operação da equipe

| Módulo | O que faz | Situação |
|---|---|---|
| Laboratório | Conversar como lead e ver por dentro: contexto, extrator, fatos, decisões, travas, ações, custo | Desenhado |
| Roteamento n8n ou cérebro | Por agente: `n8n`, `cerebro` ou `sombra` | Desenhado |
| Modo sombra | Processa sem enviar, para comparar com o n8n | Desenhado |
| Interruptor de emergência | Desligar a IA de um escritório ou de todos em um clique | **Novo** |
| Fila de pendências da equipe | Transferências, análises manuais, avisos sem resposta, com prazo | Desenhado |
| Painel de qualidade | Travas, transferências, desistência por etapa, notas do auditor | Desenhado |
| Ficha do lead | Fatos com trechos, decisões e motivo, para a equipe ver por que a IA fez o que fez | **Novo**: aproveitar `cerebro_lead_fatos` e `cerebro_lead_decisoes` |

## 6. Qualidade

| Módulo | O que faz | Situação |
|---|---|---|
| Testes das funções | Tabelas de casos, inclusive os das auditorias | Desenhado |
| Conversas simuladas | Personas por cenário, marcadas com P01 a P26 | Desenhado |
| Régua para publicar | Nenhuma mudança vai ao ar sem passar nos cenários | Desenhado |
| Auditor | Nota por conversa encerrada; integração com o projeto de auditoria existente | Desenhado |
| Erro vira teste | Ocorrência confirmada vira cenário | Desenhado |

## 7. Observabilidade

| Módulo | O que faz | Situação |
|---|---|---|
| Turno gravado e reproduzível | Entrada, contexto, saída, versão da configuração | Desenhado |
| Monitor por conta | Lead sem resposta em 10 minutos; entrada sem saída (queda) | Desenhado |
| Monitor de integrações | Helena, ZapSign, provedor de IA fora do ar | **Novo**: reaproveitar `sistemaia_servicos` e `sistemaia_incidentes` |
| Logs estruturados | Um registro por etapa do turno, com o identificador do turno | **Novo** |
| Turnos lentos | Tempo de cada etapa do turno; alerta acima do limite (hoje: análise manual de execuções acima de 3 minutos) | **Novo** |
| Alertas para quem | Equipe do escritório e equipe técnica, por canal definido | **Falta decidir** |

## 8. Segurança e LGPD

| Módulo | O que faz | Situação |
|---|---|---|
| Segredos | Chaves em cofre ou criptografadas; nada no código nem no banco em texto aberto | **Falta decidir**. Hoje: chaves da Helena e da OpenAI em colunas do cadastro do escritório, e o token de uma instância Z-API escrito na URL de nós do "Fluxo Principal" (trocar esse token) |
| Senhas e códigos | Detectados, mascarados e alertados, venha do lead ou do escritório | Desenhado |
| Dados sensíveis na saída | CPF, RG e senha nunca repetidos | Desenhado |
| Isolamento entre escritórios | Toda consulta filtrada por escritório; testes que provam isso | **Novo** |
| Retenção | Prazo para apagar conversas de quem não virou cliente | **Falta decidir** (prazo) |
| Pedido de exclusão | Atender pedido do titular (LGPD) | **Novo** |
| Acesso ao Laboratório e painéis | Login, só equipe, registro de quem mexeu | **Novo** |
| Política de identidade | Persona com nome próprio, honestidade se perguntarem se é robô | Falta decidir (seção 13 do desenho) |

## 9. Infraestrutura

| Módulo | O que faz | Situação |
|---|---|---|
| Ambientes | Desenvolvimento (banco separado, dados fictícios) e produção | **Novo**: decidir se terá homologação |
| Serviço web | Recebe webhooks e serve o Laboratório | Desenhado (Python, FastAPI) |
| Trabalhadores em segundo plano | Processam turnos, ações, lembretes; mais de um em paralelo | **Novo** |
| Agendador | Lembretes, reativação, novas tentativas, monitores | Desenhado |
| Publicação do código | Testes automáticos antes de publicar; voltar versão anterior | **Novo** |
| Hospedagem | Onde roda, com acesso ao Postgres e ao Redis | **Falta decidir** |
| Backup | O Supabase já faz do banco; conferir o plano | **Novo**: conferir |
| Documentação de operação | Como publicar, como investigar, o que fazer em queda | **Novo** |

## 10. Cobertura dos fluxos atuais

Cada fluxo do n8n e onde a função dele fica no sistema novo. Nenhum fluxo ficou sem destino.

| Fluxo | Função hoje | No sistema novo |
|---|---|---|
| Fluxo Principal (`wts-inbound-weaver`) | Recebe, buffer no Redis, mídia, cria lead e card, agentes por etapa com ferramentas, envio | Seções 1 e 2: recepção, buffer, cérebro, saída. As ferramentas de troca de etapa viram decisão em código |
| Fluxo Principal - Mensagem Enviada (`wts-outbound-weaver`) | Mensagem do humano ou da IA: pausa, reagenda reativação, grava histórico, transcreve mídia, troca de número | Classificação do evento, pausa por humano, identidade do lead, mídia enviada pela equipe |
| Troca de Departamento | Move etapa, etiquetas de departamento, card do CRM, nota, aviso | Transição decidida pelo código + ações de integração |
| Contrato | Extrai dados, gera no ZapSign ou na Tramitação, envia link, recebe assinatura, mensagem final, desliga IA | Geração do contrato e contrato assinado |
| Verificação de Contrato | Consulta o ZapSign quando o lead diz que assinou | Conferência de assinatura |
| Verifica Contrato | Vazio (só recebe e repassa) | Nada a migrar |
| Alerta Notificação | Dez auditores, um por tipo de aviso, antes de avisar a equipe; desliga IA em alguns casos | Avisos à equipe com auditor |
| Arquivos Transcrição PDF | Lê TXT, MD, Word, PDF; resume autos; auditor de desqualificação | Mídia e documentos do lead |
| FOLLOWUP e Follow Up Novo | Cria cadência, fila, envia texto ou template conforme o canal, nota no chat e no card, eventos | Follow-up e status de entrega |
| CONTAR TOKEN | Lê a execução do n8n depois de terminar, soma tokens, grava consumo; fila para as que falharam | Substituído: consumo gravado na própria chamada de IA |
| Re-Execução | Botão no painel da Helena que reenvia a última mensagem do lead | Reprocessar um atendimento |
| Backfill de leads antigos | Importa contatos e conversas | Script de manutenção |
| Webhook Front | Eventos do app da plataforma | Seção 3 |
| GERAL - SDR - CLOSER (geração antiga, Z-API) | Mesmo papel do Fluxo Principal, com `leads_dashboard`, bloqueio de lead e sincronização de canais | Não migra como está: os escritórios dele passam para o modelo do 99. Bloqueio e sincronização de canais já estão no mapa |

Coisas desses fluxos que **não** vão para o sistema novo: limpeza de execuções do n8n, ramos fixos por cliente (Sousa & Costa, Aquino, lead de teste por id), esperas fixas no lugar de checagem e a montagem de webhook falso para reprocessar.

## 11. O que os fluxos n8n refeitos já resolveram

Em novembro os fluxos do Weaver e do Geral foram refeitos (pasta `Fluxos N8N`, visão geral em `NARRATIVA_E_FUNCOES.md`). Várias regras que este mapa previa já existem lá. O código herda essas regras e as tabelas, em vez de inventar outras.

| Regra no n8n refeito | Onde entra no sistema novo |
|---|---|
| Mensagem repetida descartada pelo id por 24 horas | Recepção do webhook |
| Mensagem sempre gravada, mesmo quando a IA não atende (agente pausado, sem saldo, sem prompt, desqualificado) | Recepção; corte por saldo com nota no chat |
| Três conferências: antes da espera, depois da espera, antes de enviar; resposta descartada se chegou mensagem nova ou o atendente assumiu | Buffer e saída |
| Espera de 15 a 90 segundos pelo tamanho da mensagem | Buffer |
| Lead primeiro, card depois; um lead, um card; liga o card que já existe; trava de 2 minutos | Cadastro automático |
| Trava de canal: lead ou agente de outro cliente não é respondido | Isolamento entre escritórios |
| Erro do agente com motivo (sem crédito, chave recusada, limite, provedor fora, conversa longa) e uma nova tentativa | Camada de modelo (`gerar`) |
| Três tentativas por parte da resposta; parte que falha não para as outras | Saída |
| Troca só para frente, com a linha do lead travada; recusa segunda troca sem mensagem nova; no Geral, mínimo de mensagens antes de trocar | Transições decididas pelo código |
| `troca_pela_frase`: mede quantas vezes a IA disse a frase e não chamou a tool | Linha de base para comparar: no código a transição não depende de tool |
| Ficha do começo da conversa (`lead_memoria_resumo`) + 40 últimas mensagens + fatos do banco | Contexto do agente da etapa |
| Follow-up: até 5 por minuto, um por lead, 30 minutos entre envios, devolve com 24 horas de atraso, relê antes de enviar | Follow-up |
| Follow-up do Geral pergunta à IA se o lead pediu para ser chamado depois | Intenção `adiou` do extrator |
| Contrato: valida dados, reserva, versão, mesmo link para os mesmos dados, etapa só muda com o link gravado, `external_id` | Geração do contrato, usando `contrato_documento` |
| Assinatura: consulta quem assinou; age só quando foi o lead e só na primeira vez | Conferência de assinatura |
| Desativar IA nos quatro lugares e conferir um minuto depois | Interruptor e pausa |
| Histórico com responsável e nota no chat no máximo a cada 6 horas; central de avisos com janela de 30 minutos | Observabilidade e avisos |
| Servidor n8n com 2 workers | Trabalhadores em segundo plano (mesma lição) |

Pontos que o n8n refeito ainda não resolve e o código precisa resolver:
- **Contagem de tokens** ainda lê a execução do n8n depois de terminar.
- **Ramo de anúncio** só vale para um cliente; o código faz para todos (seção 4.5 do desenho).
- **Dias do follow-up**: decidido em 22/11, segunda a sábado, das 8h às 20h, no horário de Brasília, igual no agendamento e no envio. No código, esse vira o padrão da configuração do escritório. O JSON do Weaver foi corrigido, mas falta reimportar.
- **Religar a IA sozinha**: não existe no ar; há um SQL opcional na pasta 08.
- **Tools de troca escritas para Auxílio-Acidente**: no código a transição é por regra do produto.
- **Dados já estragados** (cards duplicados, leads sem etapa, IA desligada sem data de volta): limpeza antes da virada.

## 12. Decisões que travam o início

| # | Decisão | Trava |
|---|---|---|
| 1 | Revogar o token do Supabase colado na conversa | Segurança |
| 2 | Banco de desenvolvimento (branch ou projeto novo) | Passo 1 |
| 3 | Python como linguagem | Passo 0 |
| 4 | Quem da equipe vai acompanhar e manter o código | Passo 6 em diante |
| 5 | Hospedagem | Passo 6 |

As demais decisões ("Falta decidir") podem ser tomadas durante a construção, antes do módulo correspondente.
