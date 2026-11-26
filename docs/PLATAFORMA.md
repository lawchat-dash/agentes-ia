# Plataforma de gestão dos agentes (o "Weaver" novo)

22/11/2026. Plano do painel onde o cliente ativa e edita o próprio agente e onde a equipe LawChat cria, edita e acompanha todos. Usa o projeto `agents-lawchat-main` como referência de funcionamento, mas é sistema novo: tabelas `agentesia_*`, back-end em Python e a Helena integrada direto pela API (sem n8n).

## 1. Quem usa e o que pode

| Papel | Quem | Pode |
|---|---|---|
| `admin_lawchat` | Equipe LawChat | Tudo, em todos os escritórios: criar escritório, puxar conta da Helena, editar qualquer agente, travar instruções, ver todos os erros, **entrar como** o cliente |
| `gestor` | Dono ou responsável do escritório | Conectar a Helena, criar e ativar o próprio agente, editar instruções não travadas, ZapSign, CRM, números de teste, ver conversas e erros do escritório |
| `atendente` | Equipe do escritório | Ver conversas, pausar e devolver a IA de um lead |

Toda alteração de configuração fica registrada (quem, quando, antes e depois) e pode ser desfeita.

## 2. Arquitetura

```
Navegador (painel React)  ──►  API Python (FastAPI, /api)  ──►  Postgres (tabelas agentesia_*)
                                     │                     ──►  Helena (api.helena.run)
                                     │                     ──►  ZapSign
                                     │                     ──►  OpenAI / Anthropic
Helena (webhook)  ──────────────────►  /webhook/helena  ──►  pipeline do atendimento (já pronto)
```

- O navegador **nunca** fala com o banco, a Helena ou a ZapSign: tudo passa pela API, que confere o papel e o escritório em cada chamada.
- Login próprio (e-mail e senha, sessão assinada em cookie). Não usa o Auth do Supabase, para não disparar os gatilhos do app antigo no mesmo projeto.
- Tokens (Helena, ZapSign, OpenAI) ficam no **Supabase Vault**; as tabelas guardam só o id do segredo. O painel mostra o token mascarado.
- O mesmo servidor Python serve o painel já compilado. Em desenvolvimento, o Vite encaminha `/api` para o Python.

## 3. Jornada

### 3.1 Equipe LawChat cria o escritório
1. **Admin > Escritórios > Novo**: busca a empresa na Helena pelo Token de Parceiro (`GET core/v1/company`) ou cola o id da conta.
2. Gera o token da conta (`POST core/v1/company/{id}/tokens`) ou cola um token existente. O token vai para o Vault e é testado na hora (`GET chat/v1/channel`).
3. Cria o usuário `gestor` do escritório (e-mail e senha provisória).

### 3.2 Cliente conecta a Helena
**Integrações > Helena** mostra: token válido ou não, canais encontrados, webhook conectado ou não.
- **Conectar**: o sistema registra sozinho a assinatura de webhook na Helena (`POST core/v1/webhook/subscription`, eventos `MESSAGE_RECEIVED` e `MESSAGE_SENT`), com a URL do nosso servidor e um segredo próprio.
- **Verificar**: confere se a assinatura continua ativa, se a URL é a certa e quando chegou o último evento.

### 3.3 Cliente cria e ativa o agente
1. **Agentes > Novo**: produto (Auxílio-Acidente; outros quando existirem), canal (lista vinda da Helena, mostra quais já têm agente), nome da persona, modelo de IA.
2. O agente nasce **pausado e em teste**, com as etapas e instruções padrão do produto.
3. **Instruções**: uma aba por etapa, com a instrução padrão ou a personalizada, botão "voltar ao padrão" e histórico. Instruções travadas pela LawChat aparecem só para leitura.
4. **Honorários e mídias**: texto dos honorários (a trava só deixa a IA citar o que estiver aqui), vídeo inicial e outras mídias.
5. **Laboratório**: conversar como lead e ver por dentro (o que já existe hoje).
6. **Ativação**: números de teste → **Ativar em teste** (só esses números recebem resposta) → **Ativar para todos**. **Pausar** a qualquer momento.

### 3.4 CRM da Helena
**Integrações > CRM**: escolhe o painel (`GET crm/v2/panel?IncludeDetails=Steps`) e liga cada etapa do agente a uma etapa do painel e a uma etiqueta.
- Lead novo: cria o card na etapa ligada à `sdr` (`POST crm/v2/panel/card`), com contato e atendimento.
- Troca de etapa: move o card (`PUT crm/v3/panel/card/{id}`) e troca a etiqueta.
- Um lead, um card: antes de criar, procura o card do contato no painel.
- Falha não derruba a conversa: vira tentativa nova na fila de ações e evento.

### 3.5 ZapSign (contrato)
**Integrações > ZapSign**, em três partes, como no app atual:
1. **Token e modelos**: token no Vault, lista de modelos e variáveis `{{ }}`, modelo padrão.
2. **Dados do contrato**: cada variável do modelo ligada a um dado do lead (nome, CPF, endereço... vindos dos fatos da coleta).
3. **Depois da assinatura**: webhook da ZapSign para o nosso servidor; o lead vai para `contrato_assinado`, sai a mensagem final, o card se move e a IA se despede.
A geração em si (reserva, versão, mesmo link para os mesmos dados) segue as regras do fluxo de contrato refeito no n8n.

### 3.6 Chaves de IA e modelo
**Integrações > Chaves de IA**: o escritório usa a chave da LawChat (padrão) ou cadastra a própria chave da OpenAI. O modelo é escolhido por agente (`gpt-4.1` por padrão).

### 3.7 Acompanhar
- **Início**: agentes e estado, mensagens e conversas de hoje, erros abertos, custo do dia.
- **Conversas**: leads com etapa e estado; a ficha mostra fatos com o trecho que prova, decisões, turnos e mensagens. Botões: pausar a IA, devolver à IA, encerrar.
- **Erros**: tudo de `agentesia_eventos`, filtrado por gravidade e responsável (cliente, cadastro, provedor, lead, LawChat), com o que fazer em cada caso e botão "resolvido".

## 4. Telas

| Grupo | Tela | Rota | Papel |
|---|---|---|---|
| Fazer | Início | `/` | todos |
| Fazer | Agentes | `/agentes`, `/agentes/novo`, `/agentes/:id` | gestor, admin |
| Acompanhar | Conversas | `/conversas`, `/conversas/:id` | todos |
| Acompanhar | Erros | `/erros` | gestor, admin |
| Configurar | Integrações (Helena, CRM, ZapSign, Chaves de IA) | `/integracoes` | gestor, admin |
| Configurar | Escritório e usuários | `/configuracoes` | gestor, admin |
| LawChat | Escritórios | `/admin/escritorios` | admin |
| LawChat | Alterações | `/admin/alteracoes` | admin |

Visual: o da referência "Lia Nova", em modo claro. Fonte Figtree, números e códigos em Geist Mono, roxo `#6B35F2` como cor de ação, fundo `#F5F5F7`, cartões brancos com borda `#E5E5EA` e cantos de 14 px, barra lateral de 272 px agrupada por intenção (Fazer, Acompanhar, Configurar, LawChat).

## 5. Tabelas novas (migração 002)

| Tabela | Para quê |
|---|---|
| `agentesia_usuarios` | Login: e-mail, senha (hash scrypt), papel, escritório |
| `agentesia_integracoes` | Uma linha por escritório e tipo (`helena`, `zapsign`, `openai`, `crm`): id do segredo no Vault, configuração, situação, último teste, erro |
| `agentesia_alteracoes` | Quem mudou o quê, com antes e depois |
| `agentesia_crm_cards` | O card de cada lead na Helena |
| `agentesia_contratos` | Contrato por versão, com reserva e assinatura |
| `agentesia_acoes` | Fila de chamadas à Helena e à ZapSign, com novas tentativas |

Mais duas colunas nas tabelas do núcleo (nossas): `agentesia_agente_etapas.instrucao_travada` e `agentesia_agentes.numeros_teste`.

## 6. Ordem de construção

1. **Base** (esta etapa): login, papéis, escritórios, conexão com a Helena (token, canais, webhook), agentes (criar, instruções, ativar), erros e conversas em leitura, painel com essas telas.
2. **CRM**: mapa de etapas, criação e movimento de card pela fila de ações.
3. **ZapSign**: token, modelos, mapa de variáveis, geração, webhook de assinatura.
4. **Follow-up**: cadência por etapa, fila, envio com template no canal oficial.
5. **Admin avançado**: entrar como, histórico com desfazer, travas de instrução, custo por escritório.
