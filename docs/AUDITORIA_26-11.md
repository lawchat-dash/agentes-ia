# Auditoria geral — 26/11/2026

Cinco verificações em paralelo: isolamento entre escritórios, capacidade, cobrança de tokens, tickets antigos contra o motor novo e reclamações dos grupos de WhatsApp.

## 1. Isolamento entre escritórios
**Já protegido:** webhook por escritório com segredo; conta do payload tem de ser a do escritório da URL; canal, contato e lead sempre buscados com escritório; token do cofre do escritório; painel preso ao escritório do usuário; caches com chave por lead ou escritório.

**Em correção:**
- ALTO — link público do Controle da IA acha o escritório só pelo id da conta → passa a exigir segredo por escritório (o link cadastrado na plataforma muda).
- ALTO — contrato da ZapSign buscado sem escritório (conta ZapSign compartilhada pode cair no lead de outro escritório).
- MÉDIO — Executor não confere se o lead é do escritório da ação; token da plataforma salvo sem conferir a conta.
- BAIXO — eventos de etiqueta/card sem conferir a conta; rota global legada; FKs compostas no banco.

## 2. Capacidade
- Hoje: 1 processo, 1 réplica, pool de 10 conexões; cada ida ao banco ~200 ms (servidor no Brasil, banco em us-west-2); ~120 idas por mensagem respondida.
- Aguenta ~15–20 respostas por minuto (~20–40 conversas ativas ao mesmo tempo).
- "Erro de database" sob carga: um turno abre até 9 conexões de uma vez; a espera por conexão não tem prazo; o `/saude` usa o mesmo pool, falha, e o Easypanel reinicia o container no meio dos turnos.
- Plano: (1) `/saude` fora do pool; (2) prazo na espera por conexão + pool aquecido; (3) limite de turnos simultâneos e de consultas paralelas; (4) cache curto de escritório/canal/agente/token; (5) webhook gravado cru e processado por fila própria; (6) Executor paralelo por lead.
- Decisões do dono: mesma região para app e banco (~40× mais capacidade sem código); conferir no Supabase o tamanho do pool e se a URL usa a porta 6543.

## 3. Cobrança de tokens
**Correto:** ponto único de gravação, preço em R$ calculado uma vez no banco, débito atômico, sem cobrança em dobro; tokens de cache da OpenAI e Anthropic contados certo.

**Em correção:** áudio cobrado ~58% a menos; chamadas pagas que falham não gravadas (follow-up, origem do anúncio, resumo, PDF vazio, lotes de indexação, memória); prévia do follow-up e laboratório do agente sem registro e sem saldo; nomes das funções na tela de consumo.

**Pendente:** turno que estoura o teto perde o custo já gasto (mexe no pipeline); relatórios somam valores isentos; conferir preços da família GPT-6 e Anthropic.

**Decisão do dono:** o cliente hoje paga auditor, decisor de follow-up, nova tentativa por falha do provedor e turno descartado.

## 4. Tickets (33 categorias) contra o motor novo
15 resolvidas, 17 parciais, 1 inexistente.

Resolvidas: duplicidade/retry, desativar 15 min, crédito acabando, número errado, mensagem da equipe no contexto, PDF/tipos, follow com IA off/desqualificado/assinado, "me chama amanhã", cadência por escritório, troca de etapa, contrato duplicado, link após gerar, CEP, CPF, "já assinei", pós-assinatura.

Lacunas por impacto:
1. Webhook perdido: nada procura na plataforma o lead sem resposta; sem alerta de escritório sem webhook; sem "reprocessar". (G)
2. Follow-up ausente: sem varredura de lead parado sem follow; follow nasce desligado sem alerta. (M)
3. IA desativada respondendo: falta conferir antes da 1ª parte e no último instante do follow. (P)
4. Contrato gerado sem o lead confirmar o resumo. (M) — em correção
5. Mídia obrigatória (vídeo inicial, honorários em áudio) depende do prompt. (M)
6. IA que esquece de desqualificar. (M) — em correção
7. Sinais faltando: presencial, ligação, parceria, deficiência auditiva. (M) — em correção
8. Análise manual em vez de desqualificar por escritório; travar volta ao SDR. (P/M) — em correção
9. Avaliação do Google repetida ou após desqualificar. (P)
10. Texto do follow-up: `[nome]`, promessa de áudio, repetição. (P)

## 5. Grupos de WhatsApp (09/09–24/11)
Mais reclamado: contrato/ZapSign (~90), IA parou (~60–70), mídia (~60), desqualificação errada (~50), tokens (~40), IA desativada respondendo (~36), follow-up (~30).

Fora dos tickets:
- Volta depois de queda reabordando quem a equipe já assumiu; fila dos leads da queda sem regra.
- Erros de fatos do escritório (nome, OAB, endereço, honorários) → ficha única do escritório.
- Horário de funcionamento da IA; desligar sozinha após qualificar; botão ativar sumindo.
- Número banido/qualidade baixa; aviso antes dos limites da Meta.
- ZapSign: limite do plano, lead sem e-mail, link de login no lugar do de assinatura, contrato manual quebra a etapa.
- Painel com números diferentes da realidade; resumo do caso no card.
- Segurança: chaves e senhas coladas em texto aberto nos grupos (pedir troca e oferecer canal seguro).
- Picos: 04/11 (388 erros, timeouts) e 05/11 (queda geral, 13+ escritórios).
