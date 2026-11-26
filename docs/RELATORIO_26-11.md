# Relatório da noite de 26/11

Tudo está no GitHub (`main`, último commit 11ce49d). **Nada disso está em produção até você fazer o deploy dos apps `ia` e `painel` no Easypanel** (de preferência fora de uma conversa de teste).

**Testes:** suíte completa com banco no clone limpo: **1627 passaram e 2 falharam**.
- A falha dos Relatórios era do próprio teste, que contava com poucas contas no banco. Foi corrigida e passa.
- O teste de memória da conversa alterna entre passar e falhar no mesmo código, até no código de antes desta noite. É o banco de teste local travando com duas operações ao mesmo tempo, não defeito do sistema.

**Build:** o build do painel passou.

**OpenAI:** nada foi gasto; todos os testes usam a IA falsa.

**Produção:** as migrações 011 (índices de Execuções) e 012 (Relatórios: espelho do CRM) foram aplicadas.

---

## Motor da IA

| # | Pedido | Situação |
|---|---|---|
| 1 | Turno cortado no deploy | **Pronto.** Reserva curta (90 s) renovada a cada 30 s; ao desligar, o servidor solta o lead. O turno órfão vira erro em Erros com o que já tinha saído e quantas mensagens o lead mandou no meio, e a IA responde de novo sozinha em até ~30 s. |
| 2 | Endereço dos Correios | **Pronto.** "Encontrei seu endereço pelo CEP" + 📍 rua / bairro, cidade-UF em linhas; a pergunta do número sai em outra mensagem. |
| 3 | "13 casa" | **Pronto.** Vira número 13 + complemento "casa"; "não tem" também encerra a pergunta. No contrato, "sem complemento" fica em branco. |
| 4 | Áudio chegando depois do texto | **Pronto.** Espera depois da mídia: áudio 10 s, vídeo 12 s, imagem 3 s. |
| 5 | Troca sem nota, etiqueta ou CRM | **Pronto.** CRM automático pelas colunas fixas da conta: card na SDR quando o lead chega e, a cada troca, card na coluna do tipo, etiqueta do tipo (tirando as outras) e nota "🔄 Lead passou para o agente X". **Testado na sua conta real:** card criado, movido e nota. |
| 6 | Etiqueta repetida | **Pronto.** O motor usa o ID da etiqueta da conta. ⚠️ A etiqueta "Contrato em Elaboração" duplicada (criada no meu teste) **continua na sua conta: só apago com o seu ok.** |
| 7 | Card completo | **Pronto.** Título "👤 Nome \| 📞 Telefone"; descrição com "🕒 Entrou em" + a origem (anúncio/UTM: campanha, anúncio, conteúdo, fonte, meio, termo, link). |
| 8 | Nota dos dados do contrato | **Pronto.** "📝 Dados do contrato preenchidos pelo lead", organizada, quando todos os obrigatórios estão válidos (uma por conjunto de dados). |
| 9 | Notas de ponte | **Pronto.** Agente pausado, IA desligada no escritório, IA desativada na conversa, fora do horário, horário da equipe, créditos acabando (≤20%, 1×/dia), créditos acabaram, rajada/spam, etapa sem instrução, pediu para parar, engano e desqualificado. As notas de erro ficaram com texto leve. Sem nota para número fora da lista de teste. |
| 10 | Erros sem "Etapa do lead…" | **Pronto.** |
| 11 | Troca só avança | **Conferido.** A IA só pode mandar para os destinos de cada papel; não volta etapa e não sai de contrato assinado. |

## Alertas, follow-up e contrato

| # | Pedido | Situação |
|---|---|---|
| 12 | Alertas à equipe | **Pronto.** Todos os tipos do n8n, mais 3 novos (foto do contrato, endereço sem falar, contrato manual). O **auditor** confere antes ("na dúvida, inválido"). Válido: pausa a IA, deixa nota, avisa a equipe e manda a mensagem ao lead. O mesmo aviso sai 1× a cada 12 h por lead. "Dificuldade na assinatura" também é detectada pelo contrato (abriu e não concluiu). |
| 13 | Número oficial | **Pronto.** Aviso nunca sai por número oficial (CloudAPI/WABA): registra erro claro 1× por dia. Na tela, número oficial aparece bloqueado. |
| 14 | Motor de follow-up | **Pronto.** Verifica a cada 60 s e confere tudo antes de enviar. O **agente de follow-up decide** (enviar, adiar se o lead pediu para esperar, não enviar); **quem escreve é o agente da etapa do lead**, com a voz dele. Deixa nota "Follow-up N de T enviado". Não reenvia depois de queda. Lead parado vira tarefa. Interruptor "o agente decide" na tela. |
| 15 | Contrato assinado | **Pronto.** Webhook ZapSign:
  - confere o segredo (`x-webhook-secret` ou `?segredo=`);
  - ignora quem assinou pelo escritório;
  - acha o lead pelo token, external_id, telefone ou nome;
  - não repete.

  Depois: card em Contrato assinado, etiqueta, mensagem final, follow-ups cancelados, nota "📄 Contrato Assinado!" com o resumo e aviso à equipe com "🚀 Vamos pra cima!". "Já assinei" consulta a ZapSign; sem documento, desliga a IA e pede conferência. |
| 16 | Resumo de contrato | **Pronto.** Ferramentas → Resumo de contrato → agente: liga/desliga, prompt (o seu do Auxílio já preenchido), modelo, resumo no aviso, departamento pós-assinatura e consumo. O custo entra nos créditos. |
| 17 | TramitaSign | **Desenho pronto** em `docs/TRAMITASIGN.md`. **A API não tem documentação pública**; o desenho foi feito a partir do seu fluxo n8n. Há 12 perguntas para você (as principais: documentação/conta de teste, cliente que já existe, contrato com menor). Estimativa: 5–6 dias depois da documentação. |

## Painel

| # | Pedido | Situação |
|---|---|---|
| 18 | Execuções (superadmin) | **Pronto.** Lista ao vivo (10 s) de cada execução da IA; detalhe com mensagens que entraram, prompt (com busca), decisão, tool, resposta, eventos, tempos e custo. |
| 19 | Relatórios | **Pronto.** Menu **Relatórios → Dashboard e Rastreamento de campanhas**, recriando o dashboard do "Buscar da helena" só com as nossas tabelas (sem chamada externa ao abrir). Mostra indicadores, funil, gráficos, mapa de calor, agentes, estados, melhores anúncios, teste A/B, campanhas em alerta e detalhe do anúncio. Exporta CSV e PDF. Uma conferência leve dos cards do CRM roda a cada 15 min (formato conferido na API real). |
| 20 | Bolinha da IA na Central | **Pronto.**
  - Verde ou vermelha pulsando, arrastável.
  - Popup com desativar (até religar / 30 min / 2 h / 24 h) e reativar, com nota e etiqueta.

  **Falta você cadastrar o app na plataforma:** app de painel lateral da conversa com a URL `https://<painel>/controle-ia/ponte?id_da_conta={{id_da_conta}}&id_do_atendimento={{id_do_atendimento}}&id_do_contato={{id_do_contato}}&telefone_do_contato={{telefone_do_contato}}`. Sem isso a bolinha fica cinza e funciona pela busca. |
| 21 | Tela do agente | **Pronto.** Cliente vê Ativação, Funções e automações e Histórico; Instruções só para superadmin (o backend recusa a edição de quem não é). Atalhos Prompt/Follow-up/Base abrem dentro do agente; "Testar" virou "Histórico" (popup). Frases de transferência com texto claro. |
| 22 | Funções e automações | **Pronto.** Em abas (CRM e etiquetas, Notas, Departamento, Avisos, Contrato), já preenchidas com o "Padrão (automático)"; alterar grava regras próprias e há "Voltar ao padrão". |
| 23 | Avisos no WhatsApp | **Pronto, no design da sua referência:**
  - configuração em 3 passos: número de envio, quem recebe, ligar avisos;
  - cartões com liga/desliga;
  - "Editar mensagem" com prévia do WhatsApp;
  - "Gerenciar avisos";
  - só avisos reais, agrupados; os antigos aparecem para apagar;
  - "Enviar teste". |
| 24 | Follow-up (tela) | **Pronto.** A tela com spinner eterno era a do Weaver, que nunca existiu no nosso painel. Nova tela em Ferramentas → Follow-up: **Agentes** (ativar), **Histórico** (enviado ou não e por quê) e **Dashboard** (enviados, respostas, taxa, falhas, por dia e por tentativa). Pop-up duplicado removido. Na aba do agente, resultados e histórico. |
| 25 | Biblioteca de mídia | **Pronto.** Agora é uma tela própria (Ferramentas → Biblioteca), com arrastar e soltar, busca, filtro e prévia. |
| 26 | Velocidade | **Feito.** Esqueleto no lugar de spinner, erro aparece como mensagem com "Tentar de novo", cache nas telas novas, sem pedidos repetidos. Rotas medidas em produção (0,6–1,9 s). |

---

## O que você precisa fazer

1. **Deploy** do `ia` e do `painel` no Easypanel.
2. **Avisos no WhatsApp:** escolher o número de envio (não oficial) e quem recebe, e ligar os avisos. Hoje nenhum escritório tem aviso configurado. Ligar também a função **"Avisar a equipe"** nos agentes.
3. **Bolinha da IA:** cadastrar o app na plataforma com a URL acima.
4. **Segurança:** trocar os tokens que apareceram nos fluxos colados ontem: os `pn_` de vários clientes, o token e o Client-Token da Z-API e o segredo do webhook da ZapSign.
5. **Decidir:**
   - se apago a etiqueta duplicada "Contrato em Elaboração";
   - "muitas objeções" com 3 resistências (hoje) ou 2 (como o auditor do n8n);
   - as perguntas do TramitaSign.

## Pendências conhecidas (não bloqueiam)

- O áudio do Closer `[[audio:Como Funciona o Auxílio-Acidente]]` não tem arquivo: suba o áudio ou use texto.
- O contrato ainda não manda ao lead "o número do operacional que vai te chamar" (passos O1–O9 do n8n).
- O modelo aprovado do follow-up para número oficial é um só por agente (o n8n escolhia por etapa).
- Não há nota no card do CRM a cada follow-up; a nota fica no atendimento.
- Relatórios: os cards antigos aparecem só no quadro "Cards do CRM", não no funil, e o teste A/B não tem teste estatístico.
- Ainda resta a palavra "Helena" em 3 textos internos de erro/evento (não aparecem para o lead).
